import os
import subprocess
import sys
from pathlib import Path

def test_simple_merge(input_files, output_path):
    """
    简化版本：测试基本的音频合并功能
    """
    if not input_files:
        print("没有输入文件")
        return False
    
    # 检查输入文件是否存在且有音频
    for i, file in enumerate(input_files):
        if not os.path.exists(file):
            print(f"文件不存在: {file}")
            return False
        
        # 检查文件是否有音频流
        cmd = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0", file]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            codec = result.stdout.strip()
            if not codec:
                print(f"文件没有音频流: {file}")
                return False
            print(f"文件 {i+1}: {file} - 音频编码: {codec}")
        except subprocess.CalledProcessError as e:
            print(f"检查文件失败: {file} - {e}")
            return False
    
    # 方法1: 简单的concat（适用于相同格式的文件）
    print("\n=== 尝试方法1: 简单concat ===")
    try:
        # 创建concat列表文件
        concat_file = "/tmp/concat_list.txt"
        with open(concat_file, "w") as f:
            for file in input_files:
                f.write(f"file '{file}'\n")
        
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", f"{output_path}_concat.mp3"]
        print("运行命令:", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"方法1成功: {output_path}_concat.mp3")
            os.unlink(concat_file)
        else:
            print("方法1失败:", result.stderr)
    except Exception as e:
        print(f"方法1异常: {e}")
    
    # 方法2: 使用filter_complex进行简单合并
    print("\n=== 尝试方法2: filter_complex amix ===")
    try:
        cmd = ["ffmpeg", "-y"]
        for file in input_files:
            cmd.extend(["-i", file])
        
        if len(input_files) == 1:
            cmd.extend(["-c:a", "libmp3lame", "-q:a", "2", f"{output_path}_single.mp3"])
        else:
            # 构建amix filter
            inputs_str = "".join(f"[{i}:a]" for i in range(len(input_files)))
            filter_str = f"{inputs_str}amix=inputs={len(input_files)}:duration=longest[out]"
            cmd.extend(["-filter_complex", filter_str, "-map", "[out]", "-c:a", "libmp3lame", "-q:a", "2", f"{output_path}_amix.mp3"])
        
        print("运行命令:", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"方法2成功: {output_path}_amix.mp3")
        else:
            print("方法2失败:", result.stderr)
    except Exception as e:
        print(f"方法2异常: {e}")
    
    # 方法3: 测试单个文件转换
    print("\n=== 尝试方法3: 单文件测试 ===")
    try:
        first_file = input_files[0]
        cmd = ["ffmpeg", "-y", "-i", first_file, "-c:a", "libmp3lame", "-q:a", "2", f"{output_path}_single_test.mp3"]
        print("运行命令:", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"方法3成功: {output_path}_single_test.mp3")
        else:
            print("方法3失败:", result.stderr)
    except Exception as e:
        print(f"方法3异常: {e}")

def find_temp_files(tmp_dir):
    """查找temp_*.mp3文件"""
    files = []
    p = Path(tmp_dir)
    if not p.exists():
        print(f"目录不存在: {tmp_dir}")
        return files
    
    for f in sorted(p.glob("temp_*.mp3")):
        files.append(str(f))
    
    return files

def main():
    # 请根据实际情况修改这些路径
    tmp_dir = "/workspace/TemporaryMP3"  # 修改为你的实际路径
    output_base = "/workspace/debug_audio"
    
    print("=== 音频合并调试工具 ===")
    
    # 检查ffmpeg
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        print("✓ FFmpeg 可用")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("✗ FFmpeg 不可用，请安装ffmpeg")
        sys.exit(1)
    
    # 查找输入文件
    input_files = find_temp_files(tmp_dir)
    if not input_files:
        print(f"在 {tmp_dir} 中未找到 temp_*.mp3 文件")
        print("请确保路径正确，或者手动指定文件:")
        print("例如: python debug_audio_merge.py file1.mp3 file2.mp3 ...")
        
        # 从命令行参数获取文件
        if len(sys.argv) > 1:
            input_files = sys.argv[1:]
        else:
            sys.exit(1)
    
    print(f"找到 {len(input_files)} 个输入文件:")
    for i, f in enumerate(input_files, 1):
        print(f"  {i}. {f}")
    
    # 运行测试
    test_simple_merge(input_files, output_base)
    
    print("\n=== 检查输出文件 ===")
    for suffix in ["_concat.mp3", "_amix.mp3", "_single_test.mp3"]:
        output_file = f"{output_base}{suffix}"
        if os.path.exists(output_file):
            # 检查文件大小
            size = os.path.getsize(output_file)
            print(f"✓ {output_file} - 大小: {size} bytes")
            
            # 检查是否有音频流
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", output_file]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                duration = float(result.stdout.strip())
                print(f"  时长: {duration:.2f} 秒")
            except:
                print("  无法获取时长信息")
        else:
            print(f"✗ {output_file} - 文件不存在")

if __name__ == "__main__":
    main()