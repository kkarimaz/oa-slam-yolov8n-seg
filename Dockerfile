# CPU-only build: this machine has no NVIDIA GPU, so a plain Ubuntu base
# (instead of an nvidia/cuda devel image) keeps the image small and avoids
# needing the nvidia-container-toolkit. Swap back to an nvidia/cuda base and
# set -DWITH_CUDA=ON below if you later build on a machine with an NVIDIA GPU.
FROM ubuntu:20.04


ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Paris
RUN apt-get update && apt-get upgrade -y &&\
    # Install build tools, build dependencies and python
    apt-get install -y \
        build-essential \
        cmake \
        vim \
        git \
        wget \
        unzip \
        yasm \
        pkg-config \
        libswscale-dev \
        libtbb2 \
        libtbb-dev \
        libjpeg-dev \
        libpng-dev \
        libtiff-dev \
        libavformat-dev \
        libpq-dev \
        libxine2-dev \
        libglew-dev \
        libtiff5-dev \
        zlib1g-dev \
        libjpeg-dev \
        libavcodec-dev \
        libavformat-dev \
        libavutil-dev \
        libpostproc-dev \
        libswscale-dev \
        libeigen3-dev \
        libtbb-dev \
        libgtk2.0-dev \
        libssl1.1 \
        protobuf-compiler \
        libprotobuf-dev \
        libopenblas-dev \
        liblapack-dev \
        libepoxy-dev \
        pkg-config &&\
    rm -rf /var/lib/apt/lists/*


        

ARG OPENCV_VERSION=4.6.0
ARG NPROC=16

RUN cd /opt/ &&\
    # Download and unzip OpenCV (no opencv_contrib: the codebase doesn't use
    # any contrib-only module, so skip it to save build time/disk) and delete
    # the zip afterwards
    wget https://github.com/opencv/opencv/archive/$OPENCV_VERSION.zip &&\
    unzip $OPENCV_VERSION.zip &&\
    rm $OPENCV_VERSION.zip &&\
    # Create build folder and switch to it
    mkdir /opt/opencv-${OPENCV_VERSION}/build && cd /opt/opencv-${OPENCV_VERSION}/build &&\
    # Cmake configure
    cmake \
        -DWITH_CUDA=OFF \
        -DCMAKE_BUILD_TYPE=RELEASE \
        # Skip tests/examples/docs/python bindings: this host is very tight on
        # disk, and these aren't needed to link OA-SLAM against libopencv.
        -DBUILD_TESTS=OFF \
        -DBUILD_PERF_TESTS=OFF \
        -DBUILD_EXAMPLES=OFF \
        -DBUILD_opencv_apps=OFF \
        -DBUILD_DOCS=OFF \
        -DBUILD_opencv_python2=OFF \
        -DBUILD_opencv_python3=OFF \
        -DBUILD_JAVA=OFF \
        # Install path will be /usr/local/lib (lib is implicit)
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        .. &&\
    # Make
    # make -j"$(nproc)" && \
    make -j$NPROC && \
    # Install to /usr/local/lib
    make install && \
    ldconfig && \
    # Remove OpenCV sources and build folder
    rm -rf /opt/opencv-${OPENCV_VERSION}


RUN cd /opt &&\
    git clone https://github.com/stevenlovegrove/Pangolin.git pangolin &&\
    cd pangolin &&\
    mkdir build &&\
    cd build &&\
    cmake \
        -DCMAKE_BUILD_TYPE=RELEASE \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        .. &&\
    make -j$NPROC &&\
    make install &&\
    ldconfig && \
    rm -rf /opt/pangolin


RUN cd /opt &&\
    git clone https://github.com/davisking/dlib.git  dlib &&\
    cd dlib &&\
    mkdir build &&\
    cd build &&\
    cmake \
        -DCMAKE_BUILD_TYPE=RELEASE \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        .. &&\
    make -j$NPROC &&\
    make install &&\
    ldconfig && \
    rm -rf /opt/dlib

COPY . /opt/OA-SLAM

RUN cd /opt/OA-SLAM &&\
    cd Thirdparty &&\
    cd DBoW2 &&\
    mkdir build &&\
    cd build &&\
    cmake .. &&\
    make -j$NPROC &&\
    cd ../.. &&\
    cd g2o &&\
    mkdir build &&\
    cd build &&\
    cmake .. &&\
    make -j$NPROC &&\
    cd ../.. &&\
    cd Osmap &&\
    sh build.sh &&\
    cd ../.. &&\
    mkdir build &&\
    cd build &&\
    cmake .. &&\
    make -j$NPROC &&\
    cd ../Vocabulary &&\
    tar -xvf ORBvoc.txt.tar.gz &&\
    ldconfig
