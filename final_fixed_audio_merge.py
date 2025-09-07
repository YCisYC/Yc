import os
import re
import subprocess
import sys
from pathlib import Path

# ========== 配置 ==========
FFMPEG_BIN = r"C:\Users\Yancen\ffmpeg-8.0-essentials_build\bin\ffmpeg.exe"
FFPROBE_BIN = r"C:\Users\Yancen\ffmpeg-8.0-essentials_build\bin\ffprobe.exe"

# 如果FFmpeg在PATH中，可以使用：
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

def create_silence_file(duration_sec, output_path):
    """创建指定时长的静音文件"""
    cmd = [FFMPEG_BIN, "-y", "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100", 
           "-t", str(duration_sec), "-c:a", "libmp3lame", "-q:a", "2", output_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] 创建静音文件失败: {e.stderr}")
        return False

def build_and_run_ffmpeg_concat(inputs, processes, output_path):
    """
    使用concat方法合并音频，支持时间控制和慢速播放
    这是基于调试结果的可靠方法
    """
    try:
        # 创建临时文件目录
        temp_dir = os.path.join(os.path.dirname(output_path), "temp_processing")
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
        
        concat_files = []  # 最终要concat的文件列表
        temp_files_to_cleanup = []  # 需要清理的临时文件
        
        current_time = 0.0  # 当前时间线位置
        
        for i, proc in enumerate(processes):
            input_path = inputs[i]
            target_start_time = proc["start_sec"]
            is_slow = proc.get("slow", False)
            
            print(f"处理文件 {i+1}: {os.path.basename(input_path)}")
            print(f"  目标开始时间: {target_start_time:.3f}s, 当前时间: {current_time:.3f}s, 慢速: {is_slow}")
            
            # 如果需要在当前时间和目标开始时间之间添加静音
            if target_start_time > current_time:
                silence_duration = target_start_time - current_time
                print(f"  添加静音: {silence_duration:.3f}s")
                
                silence_file = os.path.join(temp_dir, f"silence_{i}.mp3")
                if create_silence_file(silence_duration, silence_file):
                    concat_files.append(silence_file)
                    temp_files_to_cleanup.append(silence_file)
                    current_time = target_start_time
            
            # 处理当前音频文件
            processed_file = input_path
            
            # 如果需要慢速播放，创建慢速版本
            if is_slow:
                slow_file = os.path.join(temp_dir, f"slow_{i}.mp3")
                cmd = [FFMPEG_BIN, "-y", "-i", input_path, "-filter:a", "atempo=0.8", 
                       "-c:a", "libmp3lame", "-q:a", "2", slow_file]
                print(f"  创建慢速文件: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    processed_file = slow_file
                    temp_files_to_cleanup.append(slow_file)
                    print(f"  ✅ 慢速文件创建成功")
                else:
                    print(f"  ❌ 慢速文件创建失败: {result.stderr}")
                    processed_file = input_path  # 使用原文件
            
            # 添加到concat列表
            concat_files.append(processed_file)
            
            # 更新当前时间
            file_duration = ffprobe_duration(processed_file)
            if file_duration:
                current_time += file_duration
                print(f"  文件时长: {file_duration:.3f}s, 新的当前时间: {current_time:.3f}s")
        
        print(f"\n准备合并 {len(concat_files)} 个文件:")
        for i, f in enumerate(concat_files):
            print(f"  {i+1}. {os.path.basename(f)}")
        
        # 创建concat列表文件
        concat_list_file = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for file_path in concat_files:
                # 使用绝对路径并处理反斜杠
                abs_path = os.path.abspath(file_path).replace('\\', '/')
                f.write(f"file '{abs_path}'\n")
        
        # 执行concat合并
        cmd = [FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", concat_list_file, 
               "-c", "copy", output_path]
        print(f"\n执行最终合并:")
        print(" ".join([f'"{x}"' if ' ' in x else x for x in cmd]))
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # 清理临时文件
        temp_files_to_cleanup.append(concat_list_file)
        for temp_file in temp_files_to_cleanup:
            if os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except:
                    pass
        
        # 清理临时目录（如果为空）
        try:
            os.rmdir(temp_dir)
        except:
            pass
        
        if result.returncode == 0:
            print(f"[OK] 合并完成: {output_path}")
            if os.path.exists(output_path):
                size = os.path.getsize(output_path)
                duration = ffprobe_duration(output_path)
                print(f"输出文件大小: {size} bytes")
                print(f"输出文件时长: {duration:.2f} 秒" if duration else "无法获取时长")
            return True
        else:
            print("[ERROR] concat合并失败:")
            print("stderr:", result.stderr)
            print("stdout:", result.stdout)
            return False
            
    except Exception as e:
        print(f"[ERROR] concat方法异常: {e}")
        return False

def main():
    print("=== 修复版音频合并工具 (基于concat方法) ===")
    
    # 检查ffmpeg和ffprobe是否存在
    for tool, path in [("ffmpeg", FFMPEG_BIN), ("ffprobe", FFPROBE_BIN)]:
        if not os.path.exists(path):
            print(f"[ERROR] 找不到 {tool}: {path}")
            print("请检查路径配置")
            input("按Enter键退出...")
            sys.exit(1)
    
    print(f"✅ FFmpeg 路径: {FFMPEG_BIN}")
    print(f"✅ FFprobe 路径: {FFPROBE_BIN}")
    
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

    # 5. 计算处理参数（保持原有逻辑）
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

    # 6. 使用concat方法合并
    print("\n" + "="*60)
    print("开始使用 concat 方法合并音频...")
    print("="*60)
    
    success = build_and_run_ffmpeg_concat(inputs_ordered, processes, OUTPUT_MP3)
    
    if success:
        print(f"\n🎉 合并成功！")
        print(f"输出文件: {OUTPUT_MP3}")
        print("请用播放器测试音频是否正常。")
    else:
        print(f"\n❌ 合并失败，请检查错误信息。")
    
    input("按Enter键退出...")

if __name__ == "__main__":
    main()