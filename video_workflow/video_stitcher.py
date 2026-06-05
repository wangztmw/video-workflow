"""视频拼接：将多个分镜视频合成为一个完整视频。

优先使用ffmpeg，不可用时回退到macOS AVFoundation（Swift）。
"""

from __future__ import annotations

import subprocess
import tempfile
import os
import json
from pathlib import Path


# macOS Swift脚本——使用AVFoundation拼接视频
_AVFOUNDATION_SWIFT = r'''
import AVFoundation
import Foundation

func concatVideos(_ inputPaths: [String], _ outputPath: String) -> Bool {
    let composition = AVMutableComposition()

    guard let videoTrack = composition.addMutableTrack(
        withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid
    ) else { return false }
    guard let audioTrack = composition.addMutableTrack(
        withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid
    ) else { return false }

    var currentTime = CMTime.zero

    for path in inputPaths {
        let url = URL(fileURLWithPath: path)
        let asset = AVAsset(url: url)

        guard let assetVideoTrack = asset.tracks(withMediaType: .video).first else { continue }
        guard let assetAudioTrack = asset.tracks(withMediaType: .audio).first else { continue }

        let timeRange = CMTimeRange(start: .zero, duration: asset.duration)

        do {
            try videoTrack.insertTimeRange(timeRange, of: assetVideoTrack, at: currentTime)
            try audioTrack.insertTimeRange(timeRange, of: assetAudioTrack, at: currentTime)
        } catch {
            fputs("Swift: insertTimeRange failed for \(path): \(error)\n", stderr)
            return false
        }

        currentTime = CMTimeAdd(currentTime, asset.duration)
    }

    let outURL = URL(fileURLWithPath: outputPath)
    try? FileManager.default.removeItem(at: outURL)

    guard let exportSession = AVAssetExportSession(
        asset: composition, presetName: AVAssetExportPresetMediumQuality
    ) else { return false }

    exportSession.outputURL = outURL
    exportSession.outputFileType = .mp4
    exportSession.shouldOptimizeForNetworkUse = true

    let semaphore = DispatchSemaphore(value: 0)
    exportSession.exportAsynchronously {
        semaphore.signal()
    }
    semaphore.wait()

    if exportSession.status == .completed {
        return true
    } else {
        fputs("Swift: export failed: \(exportSession.error?.localizedDescription ?? "unknown")\n", stderr)
        return false
    }
}

let args = CommandLine.arguments
if args.count < 4 {
    fputs("Usage: swift concat.swift OUTPUT INPUT1 INPUT2 ...\n", stderr)
    exit(1)
}

let output = args[1]
let inputs = Array(args.dropFirst(2))
let ok = concatVideos(inputs, output)
exit(ok ? 0 : 1)
'''


class VideoStitcher:
    """视频拼接器：ffmpeg优先，回退macOS AVFoundation"""

    def __init__(self):
        self._use_ffmpeg = False
        self._ffmpeg_path = self._find_ffmpeg()
        if self._ffmpeg_path:
            self._use_ffmpeg = True

    @staticmethod
    def _find_ffmpeg() -> str | None:
        candidates = [
            "ffmpeg", "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg",
            "/tmp/ffmpeg_bin/ffmpeg",
        ]
        for path in candidates:
            if os.path.exists(path):
                try:
                    subprocess.run([path, "-version"], capture_output=True, timeout=5, check=True)
                    return path
                except Exception:
                    continue
        return None

    def stitch(
        self,
        video_paths: list[str | Path],
        output_path: str | Path,
        add_transitions: bool = False,
        transition_duration: float = 0.5,
    ) -> str:
        """将多个视频按顺序拼接成一个"""
        video_paths = [Path(p).absolute() for p in video_paths]
        for p in video_paths:
            if not p.exists():
                raise FileNotFoundError(f"视频文件不存在: {p}")

        output_path = Path(output_path).absolute()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"[stitch] 拼接 {len(video_paths)} 个视频 -> {output_path.name}")
        for i, p in enumerate(video_paths):
            size_mb = p.stat().st_size / (1024 * 1024)
            print(f"[stitch]   [{i}] {p.name} ({size_mb:.1f}MB)")

        if self._use_ffmpeg and not add_transitions:
            result = self._concat_ffmpeg(video_paths, output_path)
        elif self._use_ffmpeg:
            result = self._concat_ffmpeg_fade(video_paths, output_path, transition_duration)
        else:
            print("[stitch] ffmpeg不可用，使用macOS AVFoundation拼接...")
            if add_transitions:
                print("[stitch] AVFoundation不支持转场，使用简单拼接")
            result = self._concat_avfoundation(video_paths, output_path)

        self._print_output_info(output_path)
        return result

    # ---- ffmpeg方式 ----

    def _concat_ffmpeg(self, paths: list[Path], output: Path) -> str:
        filelist = self._write_filelist(paths)
        try:
            result = subprocess.run(
                [self._ffmpeg_path, "-y", "-f", "concat", "-safe", "0",
                 "-i", filelist, "-c", "copy", str(output)],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                print(f"[stitch] 无损拼接失败，重新编码...")
                return self._concat_ffmpeg_reencode(paths, output)
            print(f"[stitch] ✅ 拼接完成: {output.name}")
            return str(output)
        finally:
            os.unlink(filelist)

    def _concat_ffmpeg_reencode(self, paths: list[Path], output: Path) -> str:
        filelist = self._write_filelist(paths)
        try:
            subprocess.run(
                [self._ffmpeg_path, "-y", "-f", "concat", "-safe", "0",
                 "-i", filelist, "-c:v", "libx264", "-preset", "fast",
                 "-crf", "23", "-c:a", "aac", "-pix_fmt", "yuv420p", str(output)],
                capture_output=True, text=True, timeout=300, check=True,
            )
            print(f"[stitch] ✅ 拼接完成: {output.name}")
            return str(output)
        finally:
            os.unlink(filelist)

    def _concat_ffmpeg_fade(self, paths: list[Path], output: Path, duration: float) -> str:
        if len(paths) == 1:
            return self._concat_ffmpeg(paths, output)

        filter_parts = []
        for i, p in enumerate(paths):
            dur = self._get_video_duration(p)
            offset = max(0, dur - duration)
            if i == 0:
                filter_parts.append(f"[{i}:v]fade=t=out:st={offset}:d={duration}[v{i}]")
            elif i == len(paths) - 1:
                filter_parts.append(f"[{i}:v]fade=t=in:st=0:d={duration}[v{i}]")
            else:
                filter_parts.append(
                    f"[{i}:v]fade=t=in:st=0:d={duration},"
                    f"fade=t=out:st={offset}:d={duration}[v{i}]"
                )
        concat_inputs = "".join(f"[v{i}]" for i in range(len(paths)))
        filter_parts.append(f"{concat_inputs}concat=n={len(paths)}:v=1:a=0[outv]")
        filter_graph = ";".join(filter_parts)

        cmd = [self._ffmpeg_path, "-y"]
        for p in paths:
            cmd.extend(["-i", str(p)])
        cmd.extend(["-filter_complex", filter_graph, "-map", "[outv]",
                     "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                     "-pix_fmt", "yuv420p", str(output)])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[stitch] 转场失败({result.stderr[:200]})，回退简单拼接")
            return self._concat_ffmpeg(paths, output)
        print(f"[stitch] ✅ 带转场拼接完成: {output.name}")
        return str(output)

    # ---- AVFoundation方式 (macOS原生) ----

    def _concat_avfoundation(self, paths: list[Path], output: Path) -> str:
        """使用macOS AVFoundation拼接（Swift脚本）"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".swift", delete=False, encoding="utf-8"
        ) as f:
            f.write(_AVFOUNDATION_SWIFT)
            swift_path = f.name

        try:
            result = subprocess.run(
                ["swift", swift_path, str(output)] + [str(p) for p in paths],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                raise RuntimeError(f"AVFoundation拼接失败: {stderr}")

            print(f"[stitch] ✅ AVFoundation拼接完成: {output.name}")
            return str(output)
        finally:
            os.unlink(swift_path)

    # ---- 工具 ----

    @staticmethod
    def _write_filelist(paths: list[Path]) -> str:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            for p in paths:
                f.write(f"file '{p}'\n")
            return f.name

    @staticmethod
    def _get_video_duration(path: Path) -> float:
        """获取视频时长——通过ffprobe或估算"""
        # 简单估算：文件大小 / bitrate(约1Mbps for AI videos)
        size_mb = path.stat().st_size / (1024 * 1024)
        return max(2.0, size_mb * 8 / 1.0)  # ~8 seconds per MB at 1Mbps

    def _print_output_info(self, path: Path) -> None:
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"[stitch] 输出: {size_mb:.1f}MB")
