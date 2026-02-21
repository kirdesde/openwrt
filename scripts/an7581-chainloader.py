#!/usr/bin/env python3

'''Build an AN7581 chainloader FIT image.

This script stages u-boot.bin/u-boot.dtb into a working directory,
prepends an ARM64 Linux Image header stub to u-boot.bin,
compresses the result with lzma, and invokes mkimage with the provided .its.

Usage:
  scripts/an7581-chainloader.py --build-fit <output.itb> \
    --uboot-bin <u-boot.bin> \
    --uboot-dtb <u-boot.dtb> \
    --its <an7581-uboot-chainload.its> \
    --workdir <dir> \
    --mkimage <mkimage> \
    --lzma <lzma> \
    --dtc-path <path-to-dtc-dir>
'''

import argparse
import os
import shutil
import struct
import subprocess


def build_arm64_header_stub(uboot_bin, out_img):
    MAGIC = 0x644d5241  # "ARM\x64" little-endian
    HEADER_SIZE = 0x40

    # Branch from 0x0 to 0x40:
    # B imm26 uses PC + (imm26 << 2)
    # To reach 0x40: imm26 = 0x40 / 4 = 0x10
    CODE0 = 0x14000010  # b +0x40 -> lands at 0x40
    CODE1 = 0xD503201F  # nop

    # Shim at 0x40:
    # write ASCII 'U' to UART1 (ns16550 @ 0x1fbf0000, reg-shift=2)
    # x0 = 0
    # x1 = x2 (Linux passes FDT in x2; U-Boot expects x1)
    # x2 = 0
    # branch to start of u-boot.bin
    shim = [
        0xD2A3F863,  # movz x3, #0x1fbf, lsl #16 ; x3 = 0x1fbf0000
        0x52800AA4,  # movz w4, #0x55 ; 'U'
        0xB9000064,  # str  w4, [x3, #0] ; UART THR
        0xAA1F03E0,  # mov  x0, xzr
        0xAA0203E1,  # mov  x1, x2
        0xAA1F03E2,  # mov  x2, xzr
        0x14000000,  # b <u-boot.bin> (patched below)
    ]

    SHIM_SIZE = len(shim) * 4

    text_offset = 0
    image_size = os.path.getsize(uboot_bin) + HEADER_SIZE + SHIM_SIZE
    flags = 1 << 3  # allow image base anywhere (no forced relocation)

    # Patch final branch to jump from shim end to start of u-boot.bin
    branch_pc = HEADER_SIZE + (len(shim) - 1) * 4
    target = HEADER_SIZE + SHIM_SIZE
    imm26 = (target - branch_pc) // 4
    shim[-1] = 0x14000000 | (imm26 & 0x03FFFFFF)

    hdr = struct.pack(
        "<IIQQQQQQII",
        CODE0,
        CODE1,
        text_offset,
        image_size,
        flags,
        0, 0, 0,
        MAGIC,
        0
    )

    assert len(hdr) == HEADER_SIZE

    with open(out_img, "wb") as f:
        f.write(hdr)
        f.write(struct.pack("<" + "I" * len(shim), *shim))
        with open(uboot_bin, "rb") as ub:
            f.write(ub.read())

def build_fit(output_itb, uboot_bin, uboot_dtb, its,
              workdir, mkimage, lzma, dtc_path):
    os.makedirs(workdir, exist_ok=True)

    uboot_bin_dst = os.path.join(workdir, "u-boot.bin")
    uboot_dtb_dst = os.path.join(workdir, "u-boot.dtb")
    uboot_img_dst = os.path.join(workdir, "u-boot.img")
    uboot_lzma_dst = os.path.join(workdir, "u-boot.bin.lzma")

    shutil.copy2(uboot_bin, uboot_bin_dst)
    shutil.copy2(uboot_dtb, uboot_dtb_dst)

    build_arm64_header_stub(uboot_bin_dst, uboot_img_dst)

    subprocess.run([lzma, "e", uboot_img_dst, uboot_lzma_dst], check=True)

    env = os.environ.copy()
    if dtc_path:
        env["PATH"] = f"{dtc_path}:{env.get('PATH', '')}"

    subprocess.run([
        mkimage,
        "-D", f"-i {workdir}",
        "-f", its,
        os.path.abspath(output_itb),
    ], check=True, env=env)


def main():
    parser = argparse.ArgumentParser(description="AN7581 chainloader FIT builder")
    parser.add_argument("--build-fit", dest="output_itb", required=True,
                        help="Output .itb path")
    parser.add_argument("--uboot-bin", required=True,
                        help="Path to u-boot.bin")
    parser.add_argument("--uboot-dtb", required=True,
                        help="Path to u-boot.dtb")
    parser.add_argument("--its", required=True,
                        help="Path to .its file")
    parser.add_argument("--workdir", required=True,
                        help="Working directory for staging")
    parser.add_argument("--mkimage", default="mkimage",
                        help="mkimage binary path")
    parser.add_argument("--lzma", default="lzma",
                        help="lzma binary path")
    parser.add_argument("--dtc-path", default="",
                        help="Directory containing dtc (added to PATH)")

    args = parser.parse_args()

    build_fit(
        output_itb=args.output_itb,
        uboot_bin=args.uboot_bin,
        uboot_dtb=args.uboot_dtb,
        its=args.its,
        workdir=args.workdir,
        mkimage=args.mkimage,
        lzma=args.lzma,
        dtc_path=args.dtc_path,
    )


if __name__ == "__main__":
    main()
