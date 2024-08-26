from flask import Flask, request, send_file, jsonify, send_from_directory, url_for, redirect
from hentai import Hentai, Format
from PIL import Image
from g4f.client import Client
from io import BytesIO
import requests
import subprocess
import json
import os
import random
import psutil
import threading
import time
import re
from flask_cors import CORS
from concurrent.futures import ThreadPoolExecutor
from pytubefix import Search, YouTube
from pytubefix.cli import on_progress
from werkzeug.serving import WSGIRequestHandler

app = Flask(__name__)
CORS(app)

WSGIRequestHandler.log_request = lambda *args, **kwargs: None

stats_file = 'stats.json'

client = Client()

def get_memory_usage():
    memory_info = psutil.virtual_memory()
    total_memory = memory_info.total / (1024 ** 2) 
    used_memory = (memory_info.total - memory_info.available) / (1024 ** 2) 
    return f"{used_memory:.2f}MB/{total_memory:.2f}MB"

def format_runtime(start_time):
    elapsed_time = time.time() - start_time
    days, remainder = divmod(elapsed_time, 86400) 
    hours, remainder = divmod(remainder, 3600) 
    minutes, seconds = divmod(remainder, 60)
    return f"{int(days)}d {int(hours)}h {int(minutes)}m {int(seconds)}s"

if not os.path.exists(stats_file) or os.stat(stats_file).st_size == 0:
    with open(stats_file, 'w') as f:
        json.dump({"total_requests": 0, "total_visitors": 0}, f)

def load_stats():
    with open(stats_file, 'r') as f:
        return json.load(f)

def save_stats(stats):
    with open(stats_file, 'w') as f:
        json.dump(stats, f)

@app.before_request
def count_requests():
    if request.path.startswith('/api'):
        stats = load_stats()
        stats['total_requests'] += 1
        save_stats(stats)

@app.before_request
def count_visitors():
    if request.path.startswith('/dashboard'):
        stats = load_stats()
        stats['total_visitors'] += 1
        save_stats(stats)

@app.route('/stats/ekushi/', methods=['GET'])
def get_stats():
    stats = load_stats()
    total_requests = stats['total_requests']
    total_visitors = stats['total_visitors']

    runtime = format_runtime(start_time)
    ram_usage = get_memory_usage()

    return jsonify({
        "total_requests": total_requests,
        "total_visitors": total_visitors,
        "runtime": runtime,
        "usage": ram_usage
    })

start_time = time.time()

@app.route('/')
def index():
    return redirect("https://ekushi.xyz/", code=302)

@app.route('/api/nhentai', methods=['GET'])
def get_hentai_info():
    doujin_id = request.args.get('id', type=int)
    
    if doujin_id is None:
        return jsonify({"error": "No doujin ID provided | Mana doujin ID nya?"}), 400
    
    try:
        doujin = Hentai(doujin_id)

        if not Hentai.exists(doujin.id):
            return jsonify({"error": "Doujin not found | Gak nemu doujin nya"}), 404
        
        doujin_info = {
            "1_author": "Exy",
            "2_title": doujin.title(Format.Pretty),
            "3_artist": [{"id": artist.id, "name": artist.name, "url": artist.url} for artist in doujin.artist],
            "4_tags": [tag.name for tag in doujin.tag],
            "5_upload_date": doujin.upload_date.isoformat(),
            "6_image_urls": doujin.image_urls
        }
        
        return jsonify(doujin_info)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def download_image(url):
    response = requests.get(url)
    img = Image.open(BytesIO(response.content))
    return img.convert('RGB')

@app.route('/api/nhentaipdf', methods=['GET'])
def get_hentai_pdf():
    doujin_id = request.args.get('id', type=int)
    
    if doujin_id is None:
        return jsonify({"error": "No doujin ID provided | Mana doujin ID nya?"}), 400
    
    try:
        doujin = Hentai(doujin_id)

        if not Hentai.exists(doujin.id):
            return jsonify({"error": "Doujin not found | Gak nemu doujin nya"}), 404
        
        with ThreadPoolExecutor() as executor:
            images = list(executor.map(download_image, doujin.image_urls))
        
        pdf_buffer = BytesIO()
        images[0].save(pdf_buffer, format="PDF", save_all=True, append_images=images[1:])
        pdf_buffer.seek(0)
        
        pdf_filename = f"{doujin.title(Format.Pretty)}.pdf"
        return send_file(pdf_buffer, as_attachment=True, download_name=pdf_filename, mimetype='application/pdf')
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/tiktok', methods=['GET'])
def get_tiktok_info():
    url = request.args.get('url')
    
    if not url:
        return jsonify({"error": "No TikTok URL provided | Link TikTok nya mana njir"}), 400

    try:
        encoded_url = requests.utils.quote(url)
        response = requests.get(f"https://api.agatz.xyz/api/tiktok?url={encoded_url}")

        if response.status_code != 200:
            return jsonify({"error": f"API request failed with status code {response.status_code}"}), 500

        data = response.json()
        
        if data.get('status') != 200:
            error_message = data.get('error', 'Unknown API error')
            return jsonify({"error": f"Failed to fetch TikTok data | Gagal saat memproses TikTok data"}), 500
        
        required_fields = ["title", "taken_at", "region", "id", "duration", "cover", "data", "music_info", "stats", "author"]
        if not all(field in data["data"] for field in required_fields):
            return jsonify({"error": "Something is missing | Ada yang hilang"}), 500
        
        tiktok_info = {
            "3_title": data["data"]["title"],
            "4_taken_at": data["data"]["taken_at"],
            "5_region": data["data"]["region"],
            "6_id": data["data"]["id"],
            "7_duration": data["data"]["duration"],
            "8_cover": data["data"]["cover"],
            "9_sizes": {
                "watermark": data["data"].get("size_wm", "N/A"),
                "nowatermark": data["data"].get("size_nowm", "N/A"),
                "nowatermark_hd": data["data"].get("size_nowm_hd", "N/A")
            },
            "10_video_urls": {
                "watermark": next((item["url"] for item in data["data"]["data"] if item["type"] == "watermark"), "N/A"),
                "nowatermark": next((item["url"] for item in data["data"]["data"] if item["type"] == "nowatermark"), "N/A"),
                "nowatermark_hd": next((item["url"] for item in data["data"]["data"] if item["type"] == "nowatermark_hd"), "N/A")
            },
            "11_music_info": data["data"].get("music_info", {}),
            "12_stats": data["data"].get("stats", {}),
            "2_author": data["data"].get("author", {}),
            "1_author": "Exy"
        }

        return jsonify(tiktok_info)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Request exception occurred: {str(e)}"}), 500
    except KeyError as e:
        return jsonify({"error": f"Missing expected data in API response: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Unexpected error occurred: {str(e)}"}), 500

@app.route('/api/youtube', methods=['GET'])
def get_youtube_info():
    url = request.args.get('url')
    
    if not url:
        return jsonify({"error": "No YouTube URL provided | Link YouTube nya mana?"}), 400

    try:
        yt = YouTube(url, use_oauth=True, allow_oauth_cache=True, on_progress_callback=on_progress)

        video_info = {
            "1_title": yt.title,
            "2_duration": yt.length,  
            "3_author": yt.author,  
            "4_thumbnail": yt.thumbnail_url,  
            "5_streams": [
                {
                    "1_itag": stream.itag,
                    "2_resolution": stream.resolution,
                    "3_type": stream.type,
                    "4_download_url": stream.url
                }
                for stream in yt.streams
            ]
        }
        
        return jsonify(video_info)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/instagram', methods=['GET'])
def get_instagram_info():
    url = request.args.get('url')
    
    if not url:
        return jsonify({"error": "No Instagram URL provided | Link Instagram nya mana?"}), 400

    try:
        api_url = "https://social-media-video-downloader.p.rapidapi.com/smvd/get/instagram"
        querystring = {"url": url}
        
        headers = {
            "x-rapidapi-key": "d3e82fd276mshacd2537a6ca419bp1d9d60jsnf5a12747e966",
            "x-rapidapi-host": "social-media-video-downloader.p.rapidapi.com"
        }
        
        response = requests.get(api_url, headers=headers, params=querystring)

        if response.status_code != 200:
            return jsonify({"error": f"API request failed with status code {response.status_code}"}), 500

        data = response.json()
        
        if not data.get('success', False):
            return jsonify({"error": "Failed to fetch Instagram data | Gagal saat memproses Instagram data"}), 500
        
        # Extract video link with quality "video_hd_original_0" if available
        video_link = next((link.get("link") for link in data.get("links", []) if link.get("quality") == "video_hd_original_0"), None)
        
        instagram_info = {
            "1_download_link": data.get("src_url"),
            "2_title": data.get("title"),
            "3_picture": data.get("picture"),
            "4_video": video_link,
        }

        return jsonify(instagram_info)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Request exception occurred: {str(e)}"}), 500
    except KeyError as e:
        return jsonify({"error": f"Missing expected data in API response: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Unexpected error occurred: {str(e)}"}), 500
    
@app.route('/api/spotify', methods=['GET'])
def download_spotify_song():
    song_url = request.args.get('url')
    
    if not song_url:
        return jsonify({"error": "No Spotify song URL provided | Mana link lagu Spotify nya?"}), 400
    
    try:
        url = 'https://spotify-downloader9.p.rapidapi.com/downloadSong'
        params = {'songId': song_url}

        headers = {
            'x-rapidapi-host': 'spotify-downloader9.p.rapidapi.com',
            'x-rapidapi-key': 'd3e82fd276mshacd2537a6ca419bp1d9d60jsnf5a12747e966'
        }

        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                song_info = {
                    "2_artist": data['data']['artist'],
                    "3_title": data['data']['title'],
                    "4_album": data['data']['album'],
                    "5_cover": data['data']['cover'],
                    "6_release_date": data['data']['releaseDate'],
                    "7_download_link": data['data']['downloadLink'],
                    "1_author": "Exy"
                }
                return jsonify(song_info)
            else:
                return jsonify({"error": "Request was not successful | Request gagal."}), 500
        else:
            return jsonify({"error": f"Failed to fetch data. | Gagal saat mengambil data."}), 500
    
    except Exception as e:
        return jsonify({"error": f"Unexpected error occurred: {str(e)}"}), 500
    
@app.route('/api/ytinfo', methods=['GET'])
def download_youtube_video():
    video_url = request.args.get('url')
    
    if not video_url:
        return jsonify({"error": "No video URL provided | Mana link nya?"}), 400
    
    try:
        yt = YouTube(video_url, use_oauth=True, allow_oauth_cache=True, on_progress_callback=on_progress)
        
        video_info = {
            "1_title": yt.title,
            "2_thumbnail": yt.thumbnail_url,
            "3_artist": yt.author,
            "4_views": yt.views,
            "5_duration": yt.length,
            "6_upload_date": yt.publish_date
        }
        
        return jsonify(video_info), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/youtube2', methods=['GET'])
def download_video():
    video_url = request.args.get('url')
    
    if not video_url:
        return jsonify({"error": "No video URL provided | Link nya manah?"}), 400
    
    try:
        yt = YouTube(video_url, use_oauth=True, allow_oauth_cache=True, on_progress_callback=on_progress)
        
        random_number = random.randint(1, 10000)
        video_filename = f'video_{random_number}.mp4'
        audio_filename = f'audio_{random_number}.mp4'
        output_filename = f'output_{random_number}.mp4'
        
        video_stream = yt.streams.filter(adaptive=True, file_extension='mp4', only_video=True).order_by('resolution').desc().first()
        
        if video_stream.resolution not in ['1080p', '720p', '480p', '360p']:
            video_stream = yt.streams.filter(adaptive=True, file_extension='mp4', only_video=True, resolution='1080p').first()
        
        audio_stream = yt.streams.filter(adaptive=True, file_extension='mp4', only_audio=True).order_by('abr').desc().first()
        
        video_stream.download(filename=video_filename)
        audio_stream.download(filename=audio_filename)
        
        subprocess.run([
            'ffmpeg', '-i', video_filename, '-i', audio_filename,
            '-c:v', 'copy', '-c:a', 'aac', '-strict', 'experimental',
            output_filename
        ])
        
        with open(output_filename, 'rb') as f:
            output_buffer = BytesIO(f.read())
        
        os.remove(video_filename)
        os.remove(audio_filename)
        os.remove(output_filename)
        
        output_buffer.seek(0)
        return send_file(output_buffer, as_attachment=True, download_name=f"{yt.title}_{random_number}.mp4", mimetype='video/mp4')
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/ytsv', methods=['GET'])
def search_video():
    query = request.args.get('q')

    if not query:
        return jsonify({"error": "No search query provided | Gaada judul yang dikasih"}), 400

    try:
        results = Search(query)
        video = results.videos[0] 
        video_url = video.watch_url
        
        yt = YouTube(video_url, use_oauth=True, allow_oauth_cache=True, on_progress_callback=on_progress)
        
        random_number = random.randint(1, 10000)
        sanitized_title = re.sub(r'[^a-zA-Z0-9_-]', '', yt.title).replace(' ', '_')
        video_filename = os.path.join('download', f'video_{sanitized_title}_{random_number}.mp4')
        audio_filename = os.path.join('download', f'audio_{sanitized_title}_{random_number}.mp4')
        output_filename = os.path.join('download', f'ytdl_{sanitized_title}_{random_number}.mp4')
        
        video_stream = yt.streams.filter(adaptive=True, file_extension='mp4', only_video=True).order_by('resolution').desc().first()
        
        if video_stream.resolution not in ['1080p', '720p', '480p', '360p']:
            video_stream = yt.streams.filter(adaptive=True, file_extension='mp4', only_video=True, resolution='1080p').first()
        
        audio_stream = yt.streams.filter(adaptive=True, file_extension='mp4', only_audio=True).order_by('abr').desc().first()
        
        video_stream.download(filename=video_filename)
        audio_stream.download(filename=audio_filename)
        
        subprocess.run([
            'ffmpeg', '-i', video_filename, '-i', audio_filename,
            '-c:v', 'copy', '-c:a', 'aac', '-strict', 'experimental',
            output_filename
        ])
        
        os.remove(video_filename)
        os.remove(audio_filename)
        
        download_link = f'https://api.ekushi.xyz/download/{os.path.basename(output_filename)}'
        
        return jsonify({
            "1_title": yt.title,
            "2_thumbnail": yt.thumbnail_url,
            "3_artist": yt.author,
            "4_views": yt.views,
            "5_duration": yt.length,
            "6_url": yt.watch_url,
            "7_download_link": download_link
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/youtube3', methods=['GET'])
def download_vid():
    video_url = request.args.get('url')
    
    if not video_url:
        return jsonify({"error": "No video URL provided | Link nya manah?"}), 400
    
    try:
        yt = YouTube(video_url, use_oauth=True, allow_oauth_cache=True, on_progress_callback=on_progress)
        
        random_number = random.randint(1, 10000)
        video_filename = f'download/video_{random_number}.mp4'
        audio_filename = f'download/audio_{random_number}.mp4'
        output_filename = f'download/output_{random_number}.mp4'
        
        # Create 'download' directory if it doesn't exist
        os.makedirs('download', exist_ok=True)
        
        video_stream = yt.streams.filter(adaptive=True, file_extension='mp4', only_video=True).order_by('resolution').desc().first()
        
        if video_stream.resolution not in ['720p', '480p', '360p']:
            video_stream = yt.streams.filter(adaptive=True, file_extension='mp4', only_video=True, resolution='720p').first()
        
        audio_stream = yt.streams.filter(adaptive=True, file_extension='mp4', only_audio=True).order_by('abr').desc().first()
        
        video_stream.download(filename=video_filename)
        audio_stream.download(filename=audio_filename)
        
        subprocess.run([
            'ffmpeg', '-i', video_filename, '-i', audio_filename,
            '-c:v', 'copy', '-c:a', 'aac', '-strict', 'experimental',
            output_filename
        ])
        
        # Generate download link (assuming you're hosting the files or have a method to serve them)
        download_link = f'https://api.ekushi.xyz/download/{os.path.basename(output_filename)}'
        
        # Clean up the downloaded files
        os.remove(video_filename)
        os.remove(audio_filename)
        
        return jsonify({
            "title": yt.title,
            "thumbnail": yt.thumbnail_url,
            "artist": yt.author,
            "views": yt.views,
            "duration": yt.length,
            "url": yt.watch_url,
            "download_link": download_link
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    
@app.route('/api/ytsa', methods=['GET'])
def search_audio():
    query = request.args.get('q')

    if not query:
        return jsonify({"error": "No search query provided | Gaada judul yang dikasih"}), 400

    try:
        results = Search(query)
        
        videos = [v for v in results.videos if hasattr(v, 'watch_url')]
        if not videos:
            return jsonify({"error": "No valid video results found | Tidak ada video yang ditemukan"}), 404
        
        video = videos[0]

        yt = YouTube(video.watch_url, use_oauth=True, allow_oauth_cache=True, on_progress_callback=on_progress)
        ys = yt.streams.get_audio_only()

        random_number = random.randint(1, 10000)
        sanitized_title = re.sub(r'[^a-zA-Z0-9_-]', '', yt.title).replace(' ', '_')
        audio_mp3_filename = os.path.join('download', f'audio_{sanitized_title}_{random_number}')

        ys.download(filename=audio_mp3_filename, mp3=True)

        download_link = f'https://api.ekushi.xyz/download/{os.path.basename(audio_mp3_filename)}.mp3'

        return jsonify({
            "1_title": yt.title,
            "2_thumbnail": yt.thumbnail_url,
            "3_artist": yt.author,
            "4_views": yt.views,
            "5_duration": yt.length,
            "6_url": yt.watch_url,
            "7_download_link": download_link
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/ytmp3', methods=['GET'])
def download_audio():
    video_url = request.args.get('url')

    if not video_url:
        return jsonify({"error": "No video URL provided | Link nya manah?"}), 400

    try:
        yt = YouTube(video_url, use_oauth=True, allow_oauth_cache=True, on_progress_callback=on_progress)
        
        ys = yt.streams.get_audio_only()

        random_number = random.randint(1, 10000)
        sanitized_title = re.sub(r'[^a-zA-Z0-9_-]', '', yt.title).replace(' ', '_')
        audio_mp3_filename = os.path.join('download', f'audio_{sanitized_title}_{random_number}')

        ys.download(filename=audio_mp3_filename, mp3=True)

        download_link = f'https://api.ekushi.xyz/download/{os.path.basename(audio_mp3_filename)}.mp3'

        return jsonify({
            "1_title": yt.title,
            "2_thumbnail": yt.thumbnail_url,
            "3_artist": yt.author,
            "4_views": yt.views,
            "5_duration": yt.length,
            "6_url": yt.watch_url,
            "7_download_link": download_link
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    file_path = os.path.join('download', filename)
    if not os.path.exists(file_path):
        return jsonify({"message": "More than 100 sec has passed | Sudah lewat dari 100 detik"}), 404
    return send_file(file_path, as_attachment=True, mimetype='video/mp4')

def delete_old_files():
    while True:
        time.sleep(5000)
        for filename in os.listdir('download'):
            file_path = os.path.join('download', filename)
            if (filename.startswith('ytdl_') or filename.startswith('audio_')) and (filename.endswith('.mp4') or filename.endswith('.mp3')):
                os.remove(file_path)
                print(f"Deleted {filename}")

deletion_thread = threading.Thread(target=delete_old_files, daemon=True)
deletion_thread.start()

@app.route('/api/yts', methods=['GET'])
def search_videos():
    query = request.args.get('q')

    if not query:
        return jsonify({"error": "No search query provided | Gaada judul yang dikasih"}), 400

    try:
        results = Search(query)

        if not results.videos:
            return jsonify({"error": "No videos found | Tidak ada video yang ditemukan"}), 404

        videos = []
        for video in results.videos:
            yt = YouTube(video.watch_url, use_oauth=True, allow_oauth_cache=True, on_progress_callback=on_progress)

            videos.append({
                "1_title": yt.title,
                "2_thumbnail": yt.thumbnail_url,
                "3_url": yt.watch_url,
                "4_author": yt.author,
                "5_duration": yt.length
            })

        return jsonify({"videos": videos})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/gpt3', methods=['GET'])
def gpt_3():
    query = request.args.get('q')

    if not query:
        return jsonify({"error": "No query provided | Gaada query yang dikasih"}), 400

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": query}]
        )
        
        answer = response.choices[0].message.content

        return jsonify({"response": answer})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/gpt4o', methods=['GET'])
def gpt_4o():
    query = request.args.get('q')

    if not query:
        return jsonify({"error": "No query provided | Gaada query yang dikasih"}), 400

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": query}]
        )
        
        answer = response.choices[0].message.content

        return jsonify({"response": answer})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/crplus', methods=['GET'])
def crplus():
    query = request.args.get('q')

    if not query:
        return jsonify({"error": "No query provided | Gaada query yang dikasih"}), 400

    try:
        response = client.chat.completions.create(
            model="command-r+",
            messages=[{"role": "user", "content": query}]
        )
        
        answer = response.choices[0].message.content

        return jsonify({"response": answer})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/llama3', methods=['GET'])
def llama3():
    query = request.args.get('q')

    if not query:
        return jsonify({"error": "No query provided | Gaada query yang dikasih"}), 400

    try:
        response = client.chat.completions.create(
            model="llama-3.1-70b",
            messages=[{"role": "user", "content": query}]
        )
        
        answer = response.choices[0].message.content

        return jsonify({"response": answer})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/phi3', methods=['GET'])
def phi3():
    query = request.args.get('q')

    if not query:
        return jsonify({"error": "No query provided | Gaada query yang dikasih"}), 400

    try:
        response = client.chat.completions.create(
            model="Phi-3-mini-4k-instruct",
            messages=[{"role": "user", "content": query}]
        )
        
        answer = response.choices[0].message.content

        return jsonify({"response": answer})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/mixtral', methods=['GET'])
def mixtral():
    query = request.args.get('q')

    if not query:
        return jsonify({"error": "No query provided | Gaada query yang dikasih"}), 400

    try:
        response = client.chat.completions.create(
            model="mixtral-8x7b",
            messages=[{"role": "user", "content": query}]
        )
        
        answer = response.choices[0].message.content

        return jsonify({"response": answer})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/blackbox', methods=['GET'])
def blackbox():
    query = request.args.get('q')

    if not query:
        return jsonify({"error": "No query provided | Gaada query yang dikasih"}), 400

    try:
        response = client.chat.completions.create(
            model="blackbox",
            messages=[{"role": "user", "content": query}]
        )
        
        answer = response.choices[0].message.content

        return jsonify({"response": answer})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/statistic', methods=['GET'])
def get_stats_info():
    try:
        response = requests.get("http://152.42.208.53/stats/ekushi")

        if response.status_code != 200:
            return jsonify({"error": f"API request failed with status code {response.status_code}"}), 500

        data = response.json()
        
        required_fields = ["runtime", "total_requests", "total_visitors", "usage"]
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Something is missing in the API response data | Ada yang hilang dalam data respons API"}), 500
        
        stats_info = {
            "runtime": data["runtime"],
            "total_requests": data["total_requests"],
            "total_visitors": data["total_visitors"],
            "usage": data["usage"]
        }

        return jsonify(stats_info)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Request exception occurred: {str(e)}"}), 500
    except KeyError as e:
        return jsonify({"error": f"Missing expected data in API response: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Unexpected error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
