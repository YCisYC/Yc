import os
import re
import subprocess
import sys
from pathlib import Path
from shlex import quote

# ========== 配置 ==========
# 修复：使用Linux路径和系统FFmpeg
FFMPEG_BIN = "ffmpeg"  # 使用系统PATH中的ffmpeg
FFPROBE_BIN = "ffprobe"  # 使用系统PATH中的ffprobe

# 修改为Linux路径格式（请根据实际情况调整）
SRT_PATH = "/workspace/audio_ch.srt"  # 请修改为实际路径
TMP_DIR = "/workspace/TemporaryMP3"   # 请修改为实际路径
OUTPUT_MP3 = "/workspace/audio.mp3"   # 请修改为实际路径
# ==========================

def parse_srt_start_times(srt_path):
    """
    返回 dict {index: start_seconds}，index 为 int，start_seconds 为 float（秒）。
    只读取每条字幕的开始时间。
    """
    pattern = re.compile(r"^\s*(\d+)\s*$", re.MULTILINE)
    time_pattern = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})")
    starts = {}
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()
    # iterate blocks
    blocks = re.split(r"\n\s*\n", content.strip(), flags=re.MULTILINE)
    for block in blocks:
        lines = block.strip().splitlines()
        if not lines:
            continue
        # first line may be index
        try:
            idx = int(lines[0].strip())
        except Exception:
            # try find index in block
            m = pattern.search(block)
            if not m:
                continue
            idx = int(m.group(1))
        # find time line
        mtime = None
        for ln in lines:
            m = time_pattern.search(ln)
            if m:
                mtime = m
                break
        if not mtime:
            continue
        h, mm, s, ms = int(mtime.group(1)), int(mtime.group(2)), int(mtime.group(3)), int(mtime.group(4))
        start_seconds = h*3600 + mm*60 + s + ms/1000.0
        starts[idx] = start_seconds
    return starts

def ffprobe_duration(path):
    """用 ffprobe 返回文件时长（秒，float）。若出错返回 None。"""
    cmd = [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        out = proc.stdout.strip()
        return float(out)
    except Exception as e:
        print(f"[ERROR] ffprobe 获取时长失败: {path} -> {e}")
        return None

def find_temp_files(tmp_dir):
    """
    返回 dict {index: fullpath}，索引按 temp_{i}.mp3 命名解析。
    """
    files = {}
    p = Path(tmp_dir)
    if not p.exists():
        raise FileNotFoundError(f"TemporaryMP3 文件夹不存在: {tmp_dir}")
    for f in p.iterdir():
        if not f.is_file():
            continue
        m = re.match(r"temp_(\d+)\.mp3$", f.name, re.IGNORECASE)
        if m:
            idx = int(m.group(1))
            files[idx] = str(f.resolve())
    return files

def seconds_to_ms_int(sec):
    return int(round(sec * 1000))

def build_and_run_ffmpeg(inputs, processes, output_path):
    """
    修复版本的FFmpeg命令构建
    inputs: list of input file paths in order (index 1..N)
    processes: list of dict for each input:
        {
            "slow": True/False,   # 是否以 0.8 倍速播放（即 atempo=0.8）
            "start_sec": float    # 在最终时间线上开始的秒数（audio_end）
        }
    """
    cmd = [FFMPEG_BIN, "-y"]
    # add inputs
    for inp in inputs:
        cmd.extend(["-i", inp])
    
    # build filter_complex
    filter_parts = []
    labels = []
    
    for i, proc in enumerate(processes):
        input_idx = i  # ffmpeg input index
        start_ms = seconds_to_ms_int(proc["start_sec"])
        label = f"a{i}"
        labels.append(label)
        
        # 修复：正确的adelay语法
        if proc.get("slow", False):
            # atempo slows to 0.8 -> longer duration
            if start_ms > 0:
                part = f"[{input_idx}:a]atempo=0.8,adelay=delays={start_ms}:all=1[{label}]"
            else:
                part = f"[{input_idx}:a]atempo=0.8[{label}]"
        else:
            if start_ms > 0:
                part = f"[{input_idx}:a]adelay=delays={start_ms}:all=1[{label}]"
            else:
                part = f"[{input_idx}:a]acopy[{label}]"
        filter_parts.append(part)
    
    # create amix from all labels
    if len(labels) == 1:
        # 单个输入直接输出
        filter_complex = ";".join(filter_parts)
        map_label = f"[{labels[0]}]"
    else:
        # 修复：正确的amix权重配置
        inputs_str = "".join(f"[{l}]" for l in labels)
        weights = " ".join(["1"] * len(labels))  # 每个输入权重为1
        filter_complex = ";".join(filter_parts) + f";{inputs_str}amix=inputs={len(labels)}:duration=longest:dropout_transition=0:weights='{weights}'[outa]"
        map_label = "[outa]"

    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(["-map", map_label])
    cmd.extend(["-c:a", "libmp3lame", "-q:a", "2"])
    cmd.append(output_path)
    
    # run
    print("运行 ffmpeg 命令:")
    print(" ".join(quote(x) for x in cmd))
    
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("[ERROR] ffmpeg 合并失败。stderr:")
        print(proc.stderr)
        print("stdout:")
        print(proc.stdout)
        raise RuntimeError("ffmpeg 处理失败")
    print("[OK] 合并完成:", output_path)

def main():
    # 检查ffmpeg是否可用
    try:
        subprocess.run([FFMPEG_BIN, "-version"], capture_output=True, check=True)
        subprocess.run([FFPROBE_BIN, "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[ERROR] 找不到 ffmpeg 或 ffprobe。请确保已安装并在 PATH 中。")
        print("在Ubuntu/Debian上安装: sudo apt install ffmpeg")
        print("在CentOS/RHEL上安装: sudo yum install ffmpeg")
        sys.exit(1)
    
    # 1. 解析 srt 起始时间
    if not os.path.exists(SRT_PATH):
        print(f"[ERROR] 找不到 SRT 文件：{SRT_PATH}")
        print("请修改 SRT_PATH 变量为正确的路径")
        sys.exit(1)
    
    srt_starts = parse_srt_start_times(SRT_PATH)
    if not srt_starts:
        print("[ERROR] 未解析到任何 SRT 时间。请检查文件格式。")
        sys.exit(1)
    max_srt_idx = max(srt_starts.keys())
    print(f"解析到 SRT 最大索引: {max_srt_idx}")

    # 2. 查找 TemporaryMP3 中的 temp_{i}.mp3
    tmp_files = find_temp_files(TMP_DIR)
    if not tmp_files:
        print(f"[ERROR] TemporaryMP3 文件夹中未找到任何 temp_{{i}}.mp3 文件：{TMP_DIR}")
        print("请修改 TMP_DIR 变量为正确的路径")
        sys.exit(1)
    max_tmp_idx = max(tmp_files.keys())
    print(f"TemporaryMP3 最大索引: {max_tmp_idx}")

    # 3. 比较索引是否一致
    if max_tmp_idx != max_srt_idx:
        print("[ERROR] 字幕音频未生成完成！")
        print(f"  SRT 最大索引 = {max_srt_idx}, TemporaryMP3 最大索引 = {max_tmp_idx}")
        print("程序停止。请先生成所有 temp_{i}.mp3 后重试。")
        sys.exit(2)
    print("[OK] TemporaryMP3 中的索引与 SRT 最大索引一致，开始准备合并。")

    # 4. 获取每个 temp 文件的原始时长
    durations = {}
    for idx in sorted(tmp_files.keys()):
        path = tmp_files[idx]
        d = ffprobe_duration(path)
        if d is None:
            print(f"[ERROR] 无法获取文件时长: {path}")
            sys.exit(1)
        durations[idx] = d
        print(f"temp_{idx}.mp3 原长 = {d:.3f} s")

    # 5. 按照规则计算每个片段是否 slow（0.8）以及其在最终 timeline 的 start time
    processes = []
    inputs_ordered = []
    audio_end = 0.0
    N = max_srt_idx

    for i in range(1, N+1):
        inp_path = tmp_files[i]
        orig_len = durations[i]
        inputs_ordered.append(inp_path)

        # next srt start time（若存在）
        next_start = srt_starts.get(i+1, None)

        if i == 1:
            # 起始时间固定为0
            start_time = 0.0
            gap = None
            if next_start is not None:
                gap = next_start - orig_len
            
            if gap is None:
                slow = False
                new_len = orig_len
            else:
                if gap > 3.0:
                    slow = True
                    new_len = orig_len / 0.8
                elif 0.0 < gap <= 3.0:
                    slow = False
                    new_len = orig_len
                else:  # gap <= 0
                    slow = False
                    new_len = orig_len
            
            processes.append({"slow": slow, "start_sec": start_time, "orig_len": orig_len, "new_len": new_len})
            audio_end = start_time + new_len
        else:
            # i > 1: 起始时间为当前 audio 的结束时间 audio_end
            start_time = audio_end
            gap = None
            if next_start is not None:
                gap = next_start - audio_end - orig_len
            
            if next_start is None:
                slow = False
                new_len = orig_len
            else:
                if gap > 3.0:
                    slow = True
                    new_len = orig_len / 0.8
                elif 0.0 < gap <= 3.0:
                    slow = False
                    new_len = orig_len
                else:  # gap <= 0
                    slow = False
                    new_len = orig_len
            
            processes.append({"slow": slow, "start_sec": start_time, "orig_len": orig_len, "new_len": new_len})
            audio_end = start_time + new_len

        # 输出中间信息
        print(f"[i={i}] start_time={start_time:.3f}s, orig_len={orig_len:.3f}s, slow={processes[-1]['slow']}, new_len={processes[-1]['new_len']:.3f}s, audio_end={audio_end:.3f}s")

    # 6. 使用 ffmpeg 合并
    try:
        build_and_run_ffmpeg(inputs_ordered, processes, OUTPUT_MP3)
    except Exception as e:
        print(f"[ERROR] 合并过程中发生异常: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()