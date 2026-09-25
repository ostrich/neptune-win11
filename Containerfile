FROM docker.io/library/archlinux:base AS builder

ARG DXVK_REV=404240fdacf47470b02c76d6e684639a95dc7387
ARG VIRGLRENDERER_REV=111a6d89a466f35dad9ed5fd05623aa9edc1db6d
ARG QEMU_REV=b795d6de88fc52cb6ff061e0e034be51d8e9c474

RUN pacman -Syu --noconfirm --needed \
      base-devel \
      cmake \
      curl \
      dosfstools \
      edk2-ovmf \
      git \
      glib2 \
      glslang \
      gnutls \
      libaio \
      libcap-ng \
      libdrm \
      libepoxy \
      libjpeg-turbo \
      libpng \
      libseccomp \
      libslirp \
      liburing \
      libusb \
      libx11 \
      libxcb \
      libxext \
      libxkbcommon \
      libxml2 \
      mesa \
      meson \
      mtools \
      ninja \
      openssl \
      p7zip \
      pipewire \
      pixman \
      pkgconf \
      python \
      spice \
      spice-protocol \
      swtpm \
      usbredir \
      virt-viewer \
      vulkan-headers \
      vulkan-icd-loader \
      vulkan-tools \
      wayland \
      wayland-protocols \
      wimlib \
      zstd \
    && pacman -Scc --noconfirm

COPY patches /patches

RUN git clone --filter=blob:none https://github.com/osy/dxvk.git /src/dxvk \
    && git -C /src/dxvk checkout "$DXVK_REV" \
    && git -C /src/dxvk submodule update --init --recursive \
    && git -C /src/dxvk -c user.name='neptune-win11 build' \
         -c user.email='build@localhost' am /patches/dxvk/*.patch \
    && LDFLAGS='-Wl,-rpath,$ORIGIN' meson setup /build/dxvk /src/dxvk \
         --buildtype=release \
         --prefix=/opt/neptune \
         --libdir=lib \
         -Denable_d3d8=false \
         -Denable_d3d9=false \
         -Denable_d3d10=false \
         -Denable_d3d11=true \
         -Denable_dxgi=true \
         -Dnative_glfw=disabled \
         -Dnative_sdl2=disabled \
         -Dnative_sdl3=disabled \
         -Dnative_headless=true \
    && meson compile -C /build/dxvk \
    && meson install -C /build/dxvk

RUN pacman -Syu --noconfirm --needed python-yaml \
    && git clone --filter=blob:none https://github.com/utmapp/virglrenderer.git /src/virglrenderer \
    && git -C /src/virglrenderer checkout "$VIRGLRENDERER_REV" \
    && git -C /src/virglrenderer -c user.name='neptune-win11 build' \
         -c user.email='build@localhost' am /patches/virglrenderer/*.patch \
    && PKG_CONFIG_PATH=/opt/neptune/lib/pkgconfig \
       meson setup /build/virglrenderer /src/virglrenderer \
         --buildtype=release \
         --prefix=/opt/neptune \
         --libdir=lib \
         -Dvenus=true \
         -Dneptune=true \
         -Drender-server-worker=process \
         -Dcheck-gl-errors=false \
         -Dtests=false \
         -Dvtest=false \
    && meson compile -C /build/virglrenderer \
    && meson install -C /build/virglrenderer

RUN git clone --filter=blob:none https://github.com/utmapp/qemu.git /src/qemu \
    && git -C /src/qemu checkout "$QEMU_REV" \
    && git -C /src/qemu -c user.name='neptune-win11 build' \
         -c user.email='build@localhost' am /patches/qemu/*.patch \
    && mkdir -p /build/qemu \
    && cd /build/qemu \
    && PKG_CONFIG_PATH=/opt/neptune/lib/pkgconfig \
       LDFLAGS=-Wl,-rpath,/opt/neptune/lib \
       /src/qemu/configure \
         --prefix=/opt/neptune \
         --target-list=x86_64-softmmu \
         --enable-kvm \
         --enable-spice \
         --enable-opengl \
         --enable-virglrenderer \
         --disable-werror \
         --disable-docs \
    && make -j"$(nproc)" \
    && make install

FROM docker.io/library/archlinux:base AS runtime

RUN pacman -Syu --noconfirm --needed \
      dosfstools \
      edk2-ovmf \
      glib2 \
      gnutls \
      libaio \
      libcap-ng \
      libdrm \
      libepoxy \
      libjpeg-turbo \
      libpng \
      libseccomp \
      libslirp \
      liburing \
      libusb \
      libx11 \
      libxcb \
      libxext \
      libxkbcommon \
      mesa \
      mtools \
      openssl \
      p7zip \
      pipewire \
      pixman \
      python \
      spice \
      swtpm \
      usbredir \
      virt-viewer \
      vulkan-icd-loader \
      vulkan-radeon \
      vulkan-tools \
      wimlib \
      zstd \
    && pacman -Scc --noconfirm

COPY --from=builder /opt/neptune /opt/neptune
COPY neptune_win11 /opt/neptune/app/neptune_win11
COPY unattended /opt/neptune/app/unattended

ENV PYTHONPATH=/opt/neptune/app \
    NPT_D3D11_LIBRARY_PATH=/opt/neptune/lib/libdxvk_d3d11.so \
    NPT_DXGI_LIBRARY_PATH=/opt/neptune/lib/libdxvk_dxgi.so \
    DXVK_WSI_DRIVER=Headless \
    LD_LIBRARY_PATH=/opt/neptune/lib

WORKDIR /var/lib/neptune
CMD ["python", "-m", "neptune_win11", "doctor"]
