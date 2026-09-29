#!/bin/sh
# Builds zoovm and installs it to $PREFIX/bin (default /usr/local). Run on the Mac host.
set -e
cd "$(dirname "$0")"
PREFIX="${PREFIX:-/usr/local}"
mkdir -p .build
clang -fobjc-arc -fmodules -c VNC.m -o .build/VNC.o
swiftc -O -swift-version 5 -import-objc-header VNC.h main.swift .build/VNC.o -framework Virtualization -o .build/zoovm
codesign --force --sign - --entitlements zoovm.entitlements .build/zoovm
if [ "$1" != "--no-install" ]; then
    install -d "$PREFIX/bin"
    install -m 755 .build/zoovm "$PREFIX/bin/zoovm"
    echo "installed $PREFIX/bin/zoovm"
fi
