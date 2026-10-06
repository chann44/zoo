#!/bin/sh
# Builds zoovm and installs it to $PREFIX/bin (default /usr/local). Run on the Mac host.
# ZOOVM_SIGN_IDENTITY signs with a Developer ID (hardened runtime, timestamp) for notarization; else ad-hoc.
set -e
cd "$(dirname "$0")"
PREFIX="${PREFIX:-/usr/local}"
mkdir -p .build
clang -fobjc-arc -fmodules -c VNC.m -o .build/VNC.o
swiftc -O -swift-version 5 -import-objc-header VNC.h main.swift .build/VNC.o -framework Virtualization -o .build/zoovm
if [ -n "$ZOOVM_SIGN_IDENTITY" ]; then
    codesign --force --options runtime --timestamp --sign "$ZOOVM_SIGN_IDENTITY" --entitlements zoovm.entitlements .build/zoovm
else
    codesign --force --sign - --entitlements zoovm.entitlements .build/zoovm
fi
if [ "$1" != "--no-install" ]; then
    install -d "$PREFIX/bin"
    install -m 755 .build/zoovm "$PREFIX/bin/zoovm"
    echo "installed $PREFIX/bin/zoovm"
fi
