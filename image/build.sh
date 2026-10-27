#!/bin/bash

mkdir -p ./staging

cp ../kernel/out/android_boot_a23_panel1.img ./staging/
cp ../kernel/out/android_boot_a23_panel2.img ./staging/
cp ../kernel/out/android_boot_a33_panel1.img ./staging/
cp ../kernel/out/android_boot_a33_panel2.img ./staging/
cp ../rootfs/out/images/rootfs.tar ./staging/
cp ../home/out/home.tar ./staging/

# PortMaster seed (S12ports installs this into ports.img on first boot).
# Downloaded at image-build time so it never lands in git. Skipped silently
# when offline — S12ports also accepts a user-supplied ~/.seed/PortMaster.zip.
mkdir -p ./staging/seed
if [ ! -f ./staging/seed/PortMaster.zip ]; then
    if command -v curl &> /dev/null; then
        curl -fsSL -o ./staging/seed/PortMaster.zip \
            https://github.com/PortsMaster/PortMaster-GUI/releases/latest/download/PortMaster.zip \
            && echo "PortMaster seed downloaded" \
            || { echo "Warning: PortMaster seed download failed, continuing without it." >&2; rm -f ./staging/seed/PortMaster.zip; }
    elif command -v wget &> /dev/null; then
        wget -q -O ./staging/seed/PortMaster.zip \
            https://github.com/PortsMaster/PortMaster-GUI/releases/latest/download/PortMaster.zip \
            && echo "PortMaster seed downloaded" \
            || { echo "Warning: PortMaster seed download failed, continuing without it." >&2; rm -f ./staging/seed/PortMaster.zip; }
    else
        echo "Warning: neither curl nor wget found, skipping PortMaster seed." >&2
    fi
fi
# Bundle the seed dir (may be empty when offline) so the Dockerfile step is
# unconditional.
tar -cf ./staging/seed.tar -C ./staging/seed .

mkdir -p out

if command -v podman &> /dev/null; then
    podman build --build-arg VARIANT=a23_panel1 -o ./out .
    podman build --build-arg VARIANT=a23_panel2 -o ./out .
    podman build --build-arg VARIANT=a33_panel1 -o ./out .
    podman build --build-arg VARIANT=a33_panel2 -o ./out .
elif command -v docker &> /dev/null; then
    docker buildx build --build-arg VARIANT=a23_panel1 --output type=local,dest=./out .
    docker buildx build --build-arg VARIANT=a23_panel2 --output type=local,dest=./out .
    docker buildx build --build-arg VARIANT=a33_panel1 --output type=local,dest=./out .
    docker buildx build --build-arg VARIANT=a33_panel2 --output type=local,dest=./out .
else
    echo "Error: Neither podman nor docker was found in your PATH." >&2
    exit 1
fi
echo "Done"
