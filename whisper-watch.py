#!/usr/bin/env python3

import sys
import time
import whisper
import os
import shutil
import json
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import ffmpeg

def wait_for_file_completion(file_path, timeout=30, check_interval=1):
    """Wait until file size stops changing, indicating write is complete."""
    path = Path(file_path)
    last_size = -1
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            current_size = path.stat().st_size
            if current_size == last_size and current_size > 0:
                return True
            last_size = current_size
            time.sleep(check_interval)
        except FileNotFoundError:
            return False
    return False

class TranscriptionHandler(FileSystemEventHandler):
    def __init__(self, watch_dir, pending_dir, output_dir, model):
        self.watch_dir = Path(watch_dir)
        self.pending_dir = Path(pending_dir)
        self.output_dir = Path(output_dir)
        self.model = model

    def on_created(self, event):
        if event.is_directory:
            return
        input_file = Path(event.src_path)
        
        # Ignore hidden files and system files
        if input_file.name.startswith('.') or input_file.name.startswith('._'):
            print(f"Ignoring hidden file: {event.src_path}")
            return
        # Check if file is video or audio
        if not input_file.suffix.lower() in ('.mp4', '.mkv', '.avi', '.mov', '.mp3', '.wav', '.m4a'):
            print(f"Unsupported file type: {event.src_path}")
            return

        # Skip if file doesn't exist (might have been moved already)
        if not input_file.exists():
            print(f"File no longer exists: {event.src_path}")
            return
            
        # Wait for file to be fully written
        if not wait_for_file_completion(event.src_path):
            print(f"Timeout waiting for file to be written: {event.src_path}")
            return
                
        # Double check file still exists after waiting
        if not input_file.exists():
            print(f"File disappeared after waiting: {event.src_path}")
            return

        print(f"New file detected: {event.src_path}")
        
        try:
            # Add a lock file to prevent double processing
            lock_file = input_file.with_suffix(input_file.suffix + '.processing')
            if lock_file.exists():
                print(f"File is already being processed: {event.src_path}")
                return
                
            # Create lock file
            lock_file.touch()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stats = {}
            
            # Create unique output directory
            output_folder = self.output_dir / f"{input_file.stem}_{timestamp}"
            output_folder.mkdir(parents=True, exist_ok=True)
            
            # Move original file to pending
            pending_path = self.pending_dir / input_file.name
            shutil.move(str(input_file), str(pending_path))
            
            # Extract audio if video file
            start_time = time.time()
            is_video = pending_path.suffix.lower() in ['.mp4', '.mkv', '.avi', '.mov']
            if is_video:
                audio_path = output_folder / "extracted_audio.wav"
                stream = ffmpeg.input(str(pending_path))
                stream = ffmpeg.output(stream, str(audio_path), acodec='pcm_s16le', ac=1, ar='16k')
                ffmpeg.run(stream, overwrite_output=True)
            else:
                audio_path = pending_path
            
            conversion_time = time.time() - start_time
            stats['conversion_time'] = round(conversion_time, 2)
            
            # Transcribe
            start_time = time.time()
            result = self.model.transcribe(str(audio_path))
            transcription_time = time.time() - start_time
            
            # Collect stats
            stats['transcription_time'] = round(transcription_time, 2)
            stats['detected_language'] = result.get('language', 'unknown')
            stats['timestamp'] = datetime.now().isoformat()
            
            # Write transcription
            transcript_path = output_folder / "transcription.txt"
            with open(transcript_path, "w", encoding="utf-8") as f:
                f.write(result["text"])
            
            # Write stats
            stats_path = output_folder / "stats.json"
            with open(stats_path, "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2)
            
            # Move original file to output folder
            final_media_path = output_folder / pending_path.name
            shutil.move(str(pending_path), str(final_media_path))
            
            print(f"Processing completed: {output_folder}")
            print(f"Stats: {json.dumps(stats, indent=2)}")
            
        except Exception as e:
            print(f"Error processing {event.src_path}: {str(e)}")
            # Move file back to watch directory if processing failed
            if pending_path.exists():
                shutil.move(str(pending_path), str(input_file))
        finally:
            # Always clean up lock file
            if lock_file.exists():
                lock_file.unlink()

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Watch directory for media files and transcribe them using Whisper')
    parser.add_argument('--watch-dir', type=str, 
                       default=os.getenv('WHISPER_WATCH_DIR', './watch'),
                       help='Directory to watch for new files')
    parser.add_argument('--pending-dir', type=str,
                       default=os.getenv('WHISPER_PENDING_DIR', './pending'),
                       help='Directory for files being processed')
    parser.add_argument('--output-dir', type=str,
                       default=os.getenv('WHISPER_OUTPUT_DIR', './completed'),
                       help='Directory for completed transcriptions')
    parser.add_argument('--model-size', type=str,
                       choices=['tiny', 'base', 'small', 'medium', 'large', 'turbo'],
                       default=os.getenv('WHISPER_MODEL_SIZE', 'base'),
                       help='Whisper model size to use')
    
    args = parser.parse_args()

    # Ensure all directories exist
    for directory in [args.watch_dir, args.pending_dir, args.output_dir]:
        os.makedirs(directory, exist_ok=True)

    print(f"Loading Whisper model: {args.model_size}")
    model = whisper.load_model(args.model_size)
    
    print(f"Watching directory: {args.watch_dir}")
    print(f"Pending directory: {args.pending_dir}")
    print(f"Output directory: {args.output_dir}")

    event_handler = TranscriptionHandler(
        args.watch_dir,
        args.pending_dir,
        args.output_dir,
        model
    )
    
    observer = Observer()
    observer.schedule(event_handler, args.watch_dir, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping whisper-watch...")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
