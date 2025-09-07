import os
import re
import subprocess
import sys
from pathlib import Path
from shlex import quote

# ========== 配置 ==========
# Windows路径配置
FFMPEG_BIN = r"C:\Users\Yancen\ffmpeg-8.0-essentials_build\bin\ffmpeg.exe"
FFPROBE_BIN = r"C:\Users\Yancen\ffmpeg-8.0-essentials_build\bin\ffprobe.exe"

# 如果FFmpeg在PATH中，可以直接使用：
# FFMPEG_BIN = "ffmpeg"
# FFPROBE_BIN = "ffprobe"

SRT_PATH = r"C:\Users\Yancen\Desktop\ffmpeg_project\audio_ch.srt"
TMP_DIR = r"C:\Users\Yancen\Desktop\ffmpeg_project\TemporaryMP3"
OUTPUT_MP3 = r"C:\Users\Yancen\Desktop\ffmpeg_project\audio.mp3"
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

def build_and_run_ffmpeg_method1(inputs, processes, output_path):
    """
    方法1：使用concat demuxer（推荐用于顺序播放）
    """
    try:
        # 创建临时concat文件
        concat_file = output_path + "_concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for i, proc in enumerate(processes):
                input_path = inputs[i]
                # 如果需要慢速播放，先创建慢速版本
                if proc.get("slow", False):
                    slow_file = f"{output_path}_temp_slow_{i}.mp3"
                    slow_cmd = [FFMPEG_BIN, "-y", "-i", input_path, "-filter:a", "atempo=0.8", 
                               "-c:a", "libmp3lame", "-q:a", "2", slow_file]
                    print(f"创建慢速文件 {i}: {' '.join(slow_cmd)}")
                    result = subprocess.run(slow_cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        print(f"创建慢速文件失败: {result.stderr}")
                        raise RuntimeError("创建慢速文件失败")
                    input_path = slow_file
                
                # 添加到concat列表
                abs_path = os.path.abspath(input_path).replace('\\', '/')
                f.write(f"file '{abs_path}'\n")
        
        # 执行concat
        cmd = [FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", concat_file, 
               "-c", "copy", output_path]
        print("执行concat命令:", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # 清理临时文件
        if os.path.exists(concat_file):
            os.unlink(concat_file)
        for i, proc in enumerate(processes):
            if proc.get("slow", False):
                slow_file = f"{output_path}_temp_slow_{i}.mp3"
                if os.path.exists(slow_file):
                    os.unlink(slow_file)
        
        if result.returncode == 0:
            print(f"[OK] 方法1合并完成: {output_path}")
            return True
        else:
            print(f"[ERROR] 方法1失败: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"[ERROR] 方法1异常: {e}")
        return False

def build_and_run_ffmpeg_method2(inputs, processes, output_path):
    """
    方法2：使用filter_complex（用于复杂时间控制）
    """
    try:
        cmd = [FFMPEG_BIN, "-y"]
        
        # 添加所有输入文件
        for inp in inputs:
            cmd.extend(["-i", inp])
        
        # 构建filter_complex
        filter_parts = []
        labels = []
        
        for i, proc in enumerate(processes):
            input_idx = i
            start_ms = seconds_to_ms_int(proc["start_sec"])
            label = f"a{i}"
            labels.append(label)
            
            # 构建滤镜链
            filters = []
            
            # 1. atempo（如果需要）
            if proc.get("slow", False):
                filters.append("atempo=0.8")
            
            # 2. adelay（如果需要）
            if start_ms > 0:
                filters.append(f"adelay={start_ms}|{start_ms}")  # 修复：使用正确的adelay语法
            
            # 组合滤镜
            if filters:
                filter_str = ",".join(filters)
                part = f"[{input_idx}:a]{filter_str}[{label}]"
            else:
                part = f"[{input_idx}:a]acopy[{label}]"
            
            filter_parts.append(part)
        
        # 构建amix
        if len(labels) == 1:
            filter_complex = ";".join(filter_parts)
            map_label = f"[{labels[0]}]"
        else:
            inputs_str = "".join(f"[{l}]" for l in labels)
            # 修复：使用正确的amix语法
            filter_complex = ";".join(filter_parts) + f";{inputs_str}amix=inputs={len(labels)}:duration=longest:dropout_transition=0[out]"
            map_label = "[out]"
        
        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", map_label])
        cmd.extend(["-c:a", "libmp3lame", "-q:a", "2"])
        cmd.append(output_path)
        
        print("执行filter_complex命令:")
        print(" ".join([f'"{x}"' if ' ' in x else x for x in cmd]))
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"[OK] 方法2合并完成: {output_path}")
            return True
        else:
            print(f"[ERROR] 方法2失败:")
            print("stderr:", result.stderr)
            print("stdout:", result.stdout)
            return False
            
    except Exception as e:
        print(f"[ERROR] 方法2异常: {e}")
        return False

def main():
    print("=== 修复版音频合并工具 ===")
    
    # 检查ffmpeg和ffprobe是否存在
    for tool, path in [("ffmpeg", FFMPEG_BIN), ("ffprobe", FFPROBE_BIN)]:
        if not os.path.exists(path):
            print(f"[ERROR] 找不到 {tool}: {path}")
            print("请检查路径配置或确保FFmpeg已正确安装")
            input("按Enter键退出...")
            sys.exit(1)
    
    # 测试ffmpeg版本
    try:
        result = subprocess.run([FFMPEG_BIN, "-version"], capture_output=True, check=True, text=True)
        print(f"✅ FFmpeg 可用: {FFMPEG_BIN}")
    except Exception as e:
        print(f"[ERROR] FFmpeg 测试失败: {e}")
        input("按Enter键退出...")
        sys.exit(1)
    
    # 1. 解析 srt 起始时间
    if not os.path.exists(SRT_PATH):
        print(f"[ERROR] 找不到 SRT 文件：{SRT_PATH}")
        input("按Enter键退出...")
        sys.exit(1)
    
    srt_starts = parse_srt_start_times(SRT_PATH)
    if not srt_starts:
        print("[ERROR] 未解析到任何 SRT 时间。请检查文件格式。")
        input("按Enter键退出...")
        sys.exit(1)
    max_srt_idx = max(srt_starts.keys())
    print(f"解析到 SRT 最大索引: {max_srt_idx}")

    # 2. 查找 TemporaryMP3 中的 temp_{i}.mp3
    try:
        tmp_files = find_temp_files(TMP_DIR)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        input("按Enter键退出...")
        sys.exit(1)
        
    if not tmp_files:
        print(f"[ERROR] TemporaryMP3 文件夹中未找到任何 temp_{{i}}.mp3 文件: {TMP_DIR}")
        input("按Enter键退出...")
        sys.exit(1)
    max_tmp_idx = max(tmp_files.keys())
    print(f"TemporaryMP3 最大索引: {max_tmp_idx}")

    # 3. 比较索引是否一致
    if max_tmp_idx != max_srt_idx:
        print("[ERROR] 字幕音频未生成完成！")
        print(f"  SRT 最大索引 = {max_srt_idx}, TemporaryMP3 最大索引 = {max_tmp_idx}")
        input("按Enter键退出...")
        sys.exit(2)
    print("[OK] TemporaryMP3 中的索引与 SRT 最大索引一致，开始准备合并。")

    # 4. 获取每个 temp 文件的原始时长
    durations = {}
    for idx in sorted(tmp_files.keys()):
        path = tmp_files[idx]
        d = ffprobe_duration(path)
        if d is None:
            print(f"[ERROR] 无法获取文件时长: {path}")
            input("按Enter键退出...")
            sys.exit(1)
        durations[idx] = d
        print(f"temp_{idx}.mp3 原长 = {d:.3f} s")

    # 5. 计算处理参数
    processes = []
    inputs_ordered = []
    audio_end = 0.0
    N = max_srt_idx

    for i in range(1, N+1):
        inp_path = tmp_files[i]
        orig_len = durations[i]
        inputs_ordered.append(inp_path)

        next_start = srt_starts.get(i+1, None)

        if i == 1:
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
                else:
                    slow = False
                    new_len = orig_len
            
            processes.append({"slow": slow, "start_sec": start_time, "orig_len": orig_len, "new_len": new_len})
            audio_end = start_time + new_len
        else:
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
                else:
                    slow = False
                    new_len = orig_len
            
            processes.append({"slow": slow, "start_sec": start_time, "orig_len": orig_len, "new_len": new_len})
            audio_end = start_time + new_len

        print(f"[i={i}] start_time={start_time:.3f}s, orig_len={orig_len:.3f}s, slow={processes[-1]['slow']}, new_len={processes[-1]['new_len']:.3f}s, audio_end={audio_end:.3f}s")

    # 6. 选择合并方法
    print("\n选择合并方法:")
    print("1. 方法1: Concat (推荐，简单可靠)")
    print("2. 方法2: Filter Complex (复杂时间控制)")
    print("3. 两种方法都试试")
    
    choice = input("请选择 (1/2/3，默认1): ").strip()
    if not choice:
        choice = "1"
    
    success = False
    
    if choice in ["1", "3"]:
        print("\n=== 尝试方法1: Concat ===")
        output1 = OUTPUT_MP3.replace(".mp3", "_concat.mp3")
        success1 = build_and_run_ffmpeg_method1(inputs_ordered, processes, output1)
        if success1:
            success = True
            print(f"✅ 方法1成功，输出: {output1}")
    
    if choice in ["2", "3"]:
        print("\n=== 尝试方法2: Filter Complex ===")
        output2 = OUTPUT_MP3.replace(".mp3", "_filter.mp3")
        success2 = build_and_run_ffmpeg_method2(inputs_ordered, processes, output2)
        if success2:
            success = True
            print(f"✅ 方法2成功，输出: {output2}")
    
    if success:
        print(f"\n🎉 合并完成！请检查输出文件并用播放器测试。")
    else:
        print(f"\n❌ 合并失败，请检查错误信息。")
    
    input("按Enter键退出...")

if __name__ == "__main__":
    main()