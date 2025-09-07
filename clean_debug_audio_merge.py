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
    
    print(f"\n=== 开始测试 {len(input_files)} 个文件 ===")
    
    # 检查输入文件是否存在且有音频
    for i, file in enumerate(input_files):
        if not os.path.exists(file):
            print(f"❌ 文件不存在: {file}")
            return False
        
        # 检查文件大小
        size = os.path.getsize(file)
        print(f"📁 文件 {i+1}: {os.path.basename(file)} - 大小: {size} bytes")
        
        if size == 0:
            print(f"❌ 文件为空: {file}")
            continue
        
        # 检查文件是否有音频流
        ffprobe_cmd = "ffprobe"
        # 如果系统PATH中没有ffprobe，使用完整路径
        if not check_command_available("ffprobe"):
            ffprobe_path = r"C:\Users\Yancen\ffmpeg-8.0-essentials_build\bin\ffprobe.exe"
            if os.path.exists(ffprobe_path):
                ffprobe_cmd = ffprobe_path
            else:
                print("❌ 找不到ffprobe，请检查FFmpeg安装")
                return False
        
        cmd = [ffprobe_cmd, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name,duration", "-of", "csv=p=0", file]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            output_lines = result.stdout.strip().split('\n')
            if output_lines and output_lines[0]:
                info = output_lines[0].split(',')
                codec = info[0] if len(info) > 0 else "unknown"
                duration = info[1] if len(info) > 1 else "unknown"
                print(f"✅ 音频编码: {codec}, 时长: {duration}秒")
            else:
                print(f"❌ 文件没有音频流: {file}")
                return False
        except subprocess.CalledProcessError as e:
            print(f"❌ 检查文件失败: {file}")
            print(f"   错误: {e}")
            return False
        except Exception as e:
            print(f"❌ 检查文件异常: {file} - {e}")
            return False
    
    # 确定ffmpeg命令
    ffmpeg_cmd = "ffmpeg"
    if not check_command_available("ffmpeg"):
        ffmpeg_path = r"C:\Users\Yancen\ffmpeg-8.0-essentials_build\bin\ffmpeg.exe"
        if os.path.exists(ffmpeg_path):
            ffmpeg_cmd = ffmpeg_path
        else:
            print("❌ 找不到ffmpeg，请检查FFmpeg安装")
            return False
    
    print(f"🔧 使用FFmpeg: {ffmpeg_cmd}")
    
    # 方法1: 测试单个文件转换（最基本的测试）
    print("\n=== 方法1: 单文件转换测试 ===")
    try:
        first_file = input_files[0]
        output_single = f"{output_path}_single_test.mp3"
        cmd = [ffmpeg_cmd, "-y", "-i", first_file, "-c:a", "libmp3lame", "-q:a", "2", output_single]
        print("🚀 运行命令:", " ".join([f'"{x}"' if ' ' in x else x for x in cmd]))
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            if os.path.exists(output_single) and os.path.getsize(output_single) > 0:
                print(f"✅ 方法1成功: {output_single}")
                print(f"   输出文件大小: {os.path.getsize(output_single)} bytes")
            else:
                print(f"❌ 方法1失败: 输出文件为空或不存在")
        else:
            print("❌ 方法1失败:")
            print("stderr:", result.stderr)
            print("stdout:", result.stdout)
    except Exception as e:
        print(f"❌ 方法1异常: {e}")
    
    if len(input_files) == 1:
        print("ℹ️  只有一个输入文件，跳过合并测试")
        return True
    
    # 方法2: 简单的concat（适用于相同格式的文件）
    print("\n=== 方法2: 文件列表concat ===")
    try:
        concat_file = os.path.join(os.path.dirname(output_path), "concat_list.txt")
        with open(concat_file, "w", encoding="utf-8") as f:
            for file in input_files:
                # 使用绝对路径，并处理路径中的反斜杠
                abs_path = os.path.abspath(file).replace('\\', '/')
                f.write(f"file '{abs_path}'\n")
        
        output_concat = f"{output_path}_concat.mp3"
        cmd = [ffmpeg_cmd, "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", output_concat]
        print("🚀 运行命令:", " ".join([f'"{x}"' if ' ' in x else x for x in cmd]))
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            if os.path.exists(output_concat) and os.path.getsize(output_concat) > 0:
                print(f"✅ 方法2成功: {output_concat}")
                print(f"   输出文件大小: {os.path.getsize(output_concat)} bytes")
            else:
                print(f"❌ 方法2失败: 输出文件为空或不存在")
        else:
            print("❌ 方法2失败:")
            print("stderr:", result.stderr)
        
        # 清理临时文件
        if os.path.exists(concat_file):
            os.unlink(concat_file)
            
    except Exception as e:
        print(f"❌ 方法2异常: {e}")
    
    # 方法3: 使用filter_complex进行amix合并
    print("\n=== 方法3: filter_complex amix ===")
    try:
        output_amix = f"{output_path}_amix.mp3"
        cmd = [ffmpeg_cmd, "-y"]
        for file in input_files:
            cmd.extend(["-i", file])
        
        # 构建amix filter - 简化版本
        inputs_str = "".join(f"[{i}:a]" for i in range(len(input_files)))
        filter_str = f"{inputs_str}amix=inputs={len(input_files)}:duration=longest[out]"
        cmd.extend(["-filter_complex", filter_str, "-map", "[out]", "-c:a", "libmp3lame", "-q:a", "2", output_amix])
        
        print("🚀 运行命令:", " ".join([f'"{x}"' if ' ' in x else x for x in cmd]))
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            if os.path.exists(output_amix) and os.path.getsize(output_amix) > 0:
                print(f"✅ 方法3成功: {output_amix}")
                print(f"   输出文件大小: {os.path.getsize(output_amix)} bytes")
            else:
                print(f"❌ 方法3失败: 输出文件为空或不存在")
        else:
            print("❌ 方法3失败:")
            print("stderr:", result.stderr)
    except Exception as e:
        print(f"❌ 方法3异常: {e}")
    
    return True

def check_command_available(command):
    """检查命令是否在PATH中可用"""
    try:
        subprocess.run([command, "-version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def find_temp_files(tmp_dir):
    """查找temp_*.mp3文件"""
    files = []
    p = Path(tmp_dir)
    if not p.exists():
        print(f"❌ 目录不存在: {tmp_dir}")
        return files
    
    # 查找所有temp_数字.mp3文件，并按数字排序
    temp_files = {}
    for f in p.glob("temp_*.mp3"):
        # 提取数字
        try:
            import re
            match = re.search(r'temp_(\d+)\.mp3$', f.name)
            if match:
                num = int(match.group(1))
                temp_files[num] = str(f)
        except:
            continue
    
    # 按数字顺序排序
    for num in sorted(temp_files.keys()):
        files.append(temp_files[num])
    
    return files

def main():
    print("=== 音频合并调试工具 (Windows版) ===")
    
    # 默认路径配置 - 请根据实际情况修改
    tmp_dir = r"C:\Users\Yancen\Desktop\ffmpeg_project\TemporaryMP3"
    output_base = r"C:\Users\Yancen\Desktop\ffmpeg_project\debug_audio"
    
    print(f"📁 查找目录: {tmp_dir}")
    print(f"📁 输出目录: {os.path.dirname(output_base)}")
    
    # 检查ffmpeg
    ffmpeg_available = check_command_available("ffmpeg")
    ffprobe_available = check_command_available("ffprobe")
    
    if ffmpeg_available and ffprobe_available:
        print("✅ FFmpeg 和 FFprobe 在PATH中可用")
    else:
        # 检查指定路径
        ffmpeg_path = r"C:\Users\Yancen\ffmpeg-8.0-essentials_build\bin\ffmpeg.exe"
        ffprobe_path = r"C:\Users\Yancen\ffmpeg-8.0-essentials_build\bin\ffprobe.exe"
        
        if os.path.exists(ffmpeg_path) and os.path.exists(ffprobe_path):
            print(f"✅ FFmpeg 在指定路径可用: {os.path.dirname(ffmpeg_path)}")
        else:
            print("❌ FFmpeg 不可用")
            print("请确保:")
            print("1. FFmpeg已安装并在PATH中，或者")
            print("2. 修改脚本中的FFmpeg路径")
            input("按Enter键继续...")
            return
    
    # 查找输入文件
    input_files = find_temp_files(tmp_dir)
    if not input_files:
        print(f"❌ 在 {tmp_dir} 中未找到 temp_*.mp3 文件")
        print("\n你可以:")
        print("1. 检查路径是否正确")
        print("2. 手动指定文件路径")
        print("3. 将一些mp3文件放到指定目录并重命名为temp_1.mp3, temp_2.mp3等")
        
        # 手动输入文件
        print("\n请输入要测试的mp3文件路径（一行一个，空行结束）:")
        manual_files = []
        while True:
            file_path = input("文件路径: ").strip()
            if not file_path:
                break
            if os.path.exists(file_path):
                manual_files.append(file_path)
                print(f"✅ 添加: {file_path}")
            else:
                print(f"❌ 文件不存在: {file_path}")
        
        if manual_files:
            input_files = manual_files
        else:
            print("没有有效的输入文件，退出")
            input("按Enter键退出...")
            return
    
    print(f"\n📋 找到 {len(input_files)} 个输入文件:")
    for i, f in enumerate(input_files, 1):
        print(f"  {i}. {os.path.basename(f)}")
    
    # 确保输出目录存在
    output_dir = os.path.dirname(output_base)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"✅ 创建输出目录: {output_dir}")
    
    # 运行测试
    print("\n" + "="*50)
    success = test_simple_merge(input_files, output_base)
    
    if success:
        print("\n=== 检查输出文件 ===")
        for suffix in ["_single_test.mp3", "_concat.mp3", "_amix.mp3"]:
            output_file = f"{output_base}{suffix}"
            if os.path.exists(output_file):
                size = os.path.getsize(output_file)
                print(f"✅ {os.path.basename(output_file)} - 大小: {size} bytes")
                
                # 建议用播放器测试
                print(f"   👉 请用播放器测试: {output_file}")
            else:
                print(f"❌ {os.path.basename(output_file)} - 文件不存在")
    
    print(f"\n🎯 调试完成！请检查输出目录: {output_dir}")
    input("按Enter键退出...")

if __name__ == "__main__":
    main()