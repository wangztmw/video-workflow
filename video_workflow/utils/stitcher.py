"""视频拼接：ffmpeg优先，回退macOS AVFoundation"""

from __future__ import annotations

import subprocess
import tempfile
import os
import json
from pathlib import Path

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
        let timeRange = CMTimeRange(start: .zero, duration: asset.duration)
        do {
            try videoTrack.insertTimeRange(timeRange, of: assetVideoTrack, at: currentTime)
        } catch {
            fputs("Swift: insertTimeRange failed for \(path): \(error)\n", stderr)
            return false
        }
        if let assetAudioTrack = asset.tracks(withMediaType: .audio).first {
            try? audioTrack.insertTimeRange(timeRange, of: assetAudioTrack, at: currentTime)
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
    let semaphore = DispatchSemaphore(value: 0)
    exportSession.exportAsynchronously { semaphore.signal() }
    semaphore.wait()
    return exportSession.status == .completed
}
let args = CommandLine.arguments
if args.count < 4 { exit(1) }
let ok = concatVideos(Array(args.dropFirst(1)), args[1])
exit(ok ? 0 : 1)
'''


class VideoStitcher:
    def __init__(self):
        self._ffmpeg = self._find_ffmpeg()

    @staticmethod
    def _find_ffmpeg() -> str | None:
        for path in ["ffmpeg", "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
            if os.path.exists(path):
                try:
                    subprocess.run([path, "-version"], capture_output=True, timeout=5, check=True)
                    return path
                except Exception:
                    continue
        return None

    def stitch(self, video_paths: list[Path], output: Path, fade: bool = False, fade_dur: float = 0.5) -> Path:
        video_paths = [Path(p) for p in video_paths]
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        print(f"[stitch] 拼接 {len(video_paths)} 个视频 -> {output.name}")
        for i, p in enumerate(video_paths):
            print(f"[stitch]   [{i}] {p.name} ({p.stat().st_size/1024/1024:.1f}MB)")

        if self._ffmpeg:
            result = self._ffmpeg_concat(video_paths, output, fade, fade_dur)
        else:
            print("[stitch] ffmpeg不可用，使用macOS AVFoundation...")
            result = self._avf_concat(video_paths, output)

        print(f"[stitch] 输出: {output.stat().st_size/1024/1024:.1f}MB")
        return result

    def _ffmpeg_concat(self, paths: list[Path], output: Path, fade: bool, fade_dur: float) -> Path:
        filelist = self._filelist(paths)
        try:
            r = subprocess.run(
                [self._ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", filelist,
                 "-c", "copy", str(output)],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                return self._ffmpeg_reencode(paths, output)
            return output
        finally:
            os.unlink(filelist)

    def _ffmpeg_reencode(self, paths: list[Path], output: Path) -> Path:
        filelist = self._filelist(paths)
        try:
            subprocess.run(
                [self._ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", filelist,
                 "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                 "-c:a", "aac", "-pix_fmt", "yuv420p", str(output)],
                capture_output=True, text=True, timeout=300, check=True,
            )
            return output
        finally:
            os.unlink(filelist)

    def _avf_concat(self, paths: list[Path], output: Path) -> Path:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".swift", delete=False) as f:
            f.write(_AVFOUNDATION_SWIFT)
            swift_path = f.name
        try:
            subprocess.run(
                ["swift", swift_path, str(output)] + [str(p) for p in paths],
                capture_output=True, text=True, timeout=300, check=True,
            )
            return output
        finally:
            os.unlink(swift_path)

    @staticmethod
    def _filelist(paths: list[Path]) -> str:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            for p in paths:
                f.write(f"file '{p.absolute()}'\n")
            return f.name
