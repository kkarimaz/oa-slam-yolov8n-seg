/**
 * This file is part of OA-SLAM.
 *
 * Copyright (C) 2022 Matthieu Zins <matthieu.zins@inria.fr>
 * (Inria, LORIA, Université de Lorraine)
 * OA-SLAM is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * OA-SLAM is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with OA-SLAM. If not, see <http://www.gnu.org/licenses/>.
 */

#include "ImageDetections.h"

#include <experimental/filesystem>
#include <opencv2/opencv.hpp>
#include <unordered_set>

namespace fs = std::experimental::filesystem;

namespace ORB_SLAM2
{

    std::ostream &operator<<(std::ostream &os, const Detection &det)
    {
        os << "Detection:  cat = " << det.category_id << "  score = "
           << det.score << "  bbox = " << det.bbox.transpose();
        return os;
    }

    DetectionsFromFile::DetectionsFromFile(const std::string &filename, const std::vector<int> &cats_to_ignore)
        : ImageDetectionsManager()
    {
        std::unordered_set<unsigned int> to_ignore(cats_to_ignore.begin(), cats_to_ignore.end());
        std::ifstream fin(filename);
        if (!fin.is_open())
        {
            std::cerr << "Warning failed to open file: " << filename << std::endl;
            return;
        }
        fin >> data_;

        for (auto &frame : data_)
        {
            std::string name = frame["file_name"].get<std::string>();
            name = fs::path(name).filename();
            frame_names_.push_back(name);

            std::vector<Detection::Ptr> detections;
            for (auto &d : frame["detections"])
            {
                double score = d["detection_score"].get<double>();
                unsigned int cat = d["category_id"].get<unsigned int>();
                if (to_ignore.find(cat) != to_ignore.end())
                    continue;
                auto bb = d["bbox"];
                Eigen::Vector4d bbox(bb[0], bb[1], bb[2], bb[3]);
                detections.push_back(std::shared_ptr<Detection>(new Detection(cat, score, bbox)));
            }
            detections_[name] = detections;
        }
    }

    std::vector<Detection::Ptr> DetectionsFromFile::detect(const std::string &name) const
    {
        std::string basename = fs::path(name).filename();

        if (detections_.find(basename) == detections_.end())
            return {};
        return detections_.at(basename);
    }
    std::vector<Detection::Ptr> DetectionsFromFile::detect(unsigned int idx) const
    {
        if (idx < 0 || idx >= frame_names_.size())
        {
            std::cerr << "Warning invalid index: " << idx << std::endl;
            return {};
        }
        return this->detect(frame_names_[idx]);
    }

#ifdef USE_DNN

    ObjectDetector::ObjectDetector(const std::string &model, const std::vector<int> &cats_to_ignore)
        : network_(std::make_unique<cv::dnn::Net>()), ignored_cats_(cats_to_ignore.begin(), cats_to_ignore.end()), ImageDetectionsManager()
    {
        if (model.substr(model.size() - 4) == "onnx")
            *network_ = cv::dnn::readNetFromONNX(model);
        else
            *network_ = cv::dnn::readNetFromDarknet(model + ".cfg", model + ".weights");
        // network_->setPreferableBackend(cv::dnn::DNN_BACKEND_INFERENCE_ENGINE);
        // network_->setPreferableTarget(cv::dnn::DNN_TARGET_OPENCL);
        network_->setPreferableBackend(cv::dnn::DNN_BACKEND_OPENCV);
        // network_->setPreferableTarget(cv::dnn::DNN_TARGET_CUDA);
        std::vector<cv::dnn::MatShape> inLayerShapes;
        std::vector<cv::dnn::MatShape> outLayerShapes;
        network_->getLayerShapes(cv::dnn::MatShape(), 0, inLayerShapes, outLayerShapes);

        std::vector<int> inputShape;
        inputShape.reserve(4);
        std::cout << "Input Layer Shapes:\n";
        for (const auto& inputn: inLayerShapes) {
            for (const auto input: inputn) {
                inputShape.push_back(input);
                std::cout << input << ' ';
            }
            std::cout << '\n';
        }
        std::cout << "Output Layer Shapes:\n";
        for (const auto& outputn: outLayerShapes) {
            for (const auto output: outputn) {
                std::cout << output << ' ';
            }
            std::cout << '\n';
        }
        INPUT_HEIGHT_ = inputShape[2]; // I don't know the order, is it height and then width? 
        INPUT_WIDTH_ = inputShape[3];
    }

    std::vector<Detection::Ptr> ObjectDetector::detect(cv::Mat img) const
{
        const float SCORE_THRESHOLD = 0.5;
        const float NMS_THRESHOLD = 0.45;
        const int NUM_MASK_COEFS = 32; // yolov8n-seg punya 32 prototype masks

        cv::Mat result;
        cv::dnn::blobFromImage(img, result, 1.0 / 255, cv::Size(INPUT_WIDTH_, INPUT_HEIGHT_), cv::Scalar(), true, false);

        // Ambil SEMUA output layer (yolov8n-seg punya 2: deteksi + prototypes)
        std::vector<cv::Mat> predictions;
        network_->setInput(result);
        network_->forward(predictions, network_->getUnconnectedOutLayersNames());

        // output0: deteksi — shape [1, 4+nc+32, 8400]
        // output1: prototype masks — shape [1, 32, 160, 160]
        cv::Mat output = predictions[0];
        cv::Mat protos = predictions[1]; // shape: [1, 32, mask_h, mask_w]

        // YOLOv8 output: cols > rows, perlu di-transpose
        // setelah transpose: rows = 8400 (kandidat), cols = 4+nc+32
        int rows = output.size[1];
        int cols = output.size[2];
        if (cols > rows)
        {
            rows = output.size[2];
            cols = output.size[1];
            output = output.reshape(1, cols);
            cv::transpose(output, output);
        }

        // Jumlah kelas = total kolom - 4 (bbox) - 32 (mask coefs)
        int num_classes = cols - 4 - NUM_MASK_COEFS;

        float x_factor = (float)(img.cols) / INPUT_WIDTH_;
        float y_factor = (float)(img.rows) / INPUT_HEIGHT_;
        float *data = (float *)output.data;

        std::vector<int> class_ids;
        std::vector<float> confidences;
        std::vector<cv::Rect> boxes;
        std::vector<std::vector<float>> mask_coefs_list; // simpan koefisien mask tiap kandidat

        for (int i = 0; i < rows; ++i)
        {
            // Kolom 0-3: x, y, w, h (posisi)
            // Kolom 4 sampai 4+num_classes-1: skor per kelas
            // Kolom 4+num_classes sampai akhir: 32 mask coefficients
            float *classes_scores = data + 4;
            cv::Mat scores(1, num_classes, CV_32FC1, classes_scores);
            cv::Point class_id;
            double max_class_score;
            minMaxLoc(scores, 0, &max_class_score, 0, &class_id);

            if (ignored_cats_.count(class_id.x) == 0 && max_class_score > SCORE_THRESHOLD)
            {
                confidences.push_back(max_class_score);
                class_ids.push_back(class_id.x);

                float x = data[0], y = data[1], w = data[2], h = data[3];
                int left  = int((x - 0.5f * w) * x_factor);
                int top   = int((y - 0.5f * h) * y_factor);
                boxes.push_back(cv::Rect(left, top, int(w * x_factor), int(h * y_factor)));

                // Simpan 32 mask coefficients untuk kandidat ini
                std::vector<float> coefs(data + 4 + num_classes, data + 4 + num_classes + NUM_MASK_COEFS);
                mask_coefs_list.push_back(coefs);
            }
            data += cols;
        }

        // NMS: buang kotak yang overlap
        std::vector<int> nms_result;
        cv::dnn::NMSBoxes(boxes, confidences, SCORE_THRESHOLD, NMS_THRESHOLD, nms_result);

        // Ukuran prototype mask (biasanya 160x160)
        int proto_h = protos.size[2];
        int proto_w = protos.size[3];
        // Reshape protos dari [1, 32, 160, 160] menjadi [32, 160*160]
        cv::Mat protos_2d = protos.reshape(1, NUM_MASK_COEFS); // [32, 160*160]

        std::vector<Detection::Ptr> detections;
        for (int i = 0; i < (int)nms_result.size(); i++)
        {
            int idx = nms_result[i];
            cv::Rect &bb = boxes[idx];

            // --- Hitung mask ---
            // 1. mask_coefs [1x32] × protos_2d [32×25600] = raw_mask [1×25600]
            cv::Mat coefs_mat(1, NUM_MASK_COEFS, CV_32FC1, mask_coefs_list[idx].data());
            cv::Mat raw_mask = coefs_mat * protos_2d; // [1, 160*160]
            raw_mask = raw_mask.reshape(1, proto_h);  // [160, 160]

            // 2. Sigmoid: ubah nilai mentah jadi probabilitas 0-1
            cv::exp(-raw_mask, raw_mask);
            raw_mask = 1.0f / (1.0f + raw_mask);

            // 3. Resize mask dari 160x160 ke ukuran gambar asli
            cv::Mat mask_full;
            cv::resize(raw_mask, mask_full, cv::Size(img.cols, img.rows));

            // 4. Crop mask sesuai bbox, lalu threshold jadi binary (0 atau 255)
            cv::Mat mask_final = cv::Mat::zeros(img.rows, img.cols, CV_8UC1);
            cv::Rect safe_bb(
                std::max(bb.x, 0), std::max(bb.y, 0),
                std::min(bb.width,  img.cols - std::max(bb.x, 0)),
                std::min(bb.height, img.rows - std::max(bb.y, 0))
            );
            if (safe_bb.width > 0 && safe_bb.height > 0)
            {
                cv::Mat roi = mask_full(safe_bb);
                cv::Mat roi_thresh;
                cv::threshold(roi, roi_thresh, 0.5, 255, cv::THRESH_BINARY);
                roi_thresh.convertTo(mask_final(safe_bb), CV_8UC1);
            }

            Eigen::Vector4d bbox(bb.x, bb.y, bb.x + bb.width, bb.y + bb.height);
            detections.push_back(std::make_shared<Detection>(class_ids[idx], confidences[idx], bbox, mask_final));
        }
        return detections;
    }

#endif

}
