import twitchio
import asyncio
import sqlite3
import pygame
import random
import sys
import re
import os

from pytube import YouTube
from pydub import AudioSegment

# Global flag to indicate if the song should stop playing
stop_song = False
song_playing = False
played_songs = []  # List to track the songs that have been played
num_of_songs = 0
song_queue = []

# Valid users who can overide song requests
valid_users = ['stststudar', 'tienzoog']

# Establish a connection to the SQLite database
conn = sqlite3.connect("song_bot.db")
cursor = conn.cursor()

# Create the downloads table if it doesn't exist
cursor.execute("""
    CREATE TABLE IF NOT EXISTS downloads (
        video_id TEXT PRIMARY KEY
    )
""")

# Create the users table if it doesn't exist
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT,
        video_id TEXT,
        FOREIGN KEY (video_id) REFERENCES downloads(video_id)
    )
""")

# Play the current song
async def play_mp3(file_path):
    pygame.mixer.init()
    pygame.mixer.music.load(file_path)
    pygame.mixer.music.play()
    
    global song_playing
    song_playing = True

    while pygame.mixer.music.get_busy() and not stop_song:
        await asyncio.sleep(1)
        # continue

    # Stop the song if it's still playing
    pygame.mixer.music.stop()
    song_playing = False

# Download the song as an mp3 based on code
async def download_video_as_mp3(video_code):
    url = "https://www.youtube.com/watch?v={}".format(video_code)
    file_name = "{}.mp3".format(video_code)
    download_location = "downloaded_songs"
    output_path = os.path.join(download_location, file_name)  # Construct the output path

    print("downloading", file_name)
    yt = YouTube(url)
    audio_stream = yt.streams.filter(only_audio=True).first()
    audio_file = audio_stream.download()
    audio = AudioSegment.from_file(audio_file)
    audio.export(output_path, format="mp3")

    # Remove the .mp4 version of the file
    os.remove(audio_file)
     
    return output_path

# Download a request song for the user
async def download_song_request(message, video_id):

    # Verfiy that !song code is valid

    # Regular expression pattern for valid YouTube video codes
    code_pattern = r'\b([A-Za-z0-9_-]{11})\b'

    # Search for valid YouTube video codes in the message content
    code_match = re.search(code_pattern, video_id)

    if not code_match:
        # Invalid input, handle it accordingly
        print('Invalid input')
        return

    # Check if the video ID has already been downloaded
    cursor.execute("SELECT video_id FROM downloads WHERE video_id = ?", (video_id,))
    result = cursor.fetchone()

    global song_queue
    song_queue.append(video_id)

    if result:
        # Video has already been downloaded, link user to the video ID
       cursor.execute("INSERT INTO users (username, video_id) VALUES (?, ?)", (message.author.name, video_id))

       print("Song downloaded all ready")
    else:

       # Download the song based on the video ID
       output_path = await download_video_as_mp3(video_id)

       # Insert the video ID into the downloads table
       cursor.execute("INSERT INTO downloads (video_id) VALUES (?)", (video_id,))
       # Link the user to the downloaded video ID
       cursor.execute("INSERT INTO users (username, video_id) VALUES (?, ?)", (message.author.name, video_id))

       global num_of_songs
       num_of_songs += 1

       # Commit the changes to the database
    conn.commit()

class Bot(twitchio.Client):
    def __init__(self, twitch_token):
        # Set up TwitchIO client
        super().__init__(token=twitch_token, initial_channels=['Stststudar'])

    async def event_ready(self):
        print(f'Logged in as {self.nick}')
        self.loop.create_task(self.play_song_requests())
        # asyncio.run(self.play_song_requests())

    async def event_message(self, message):

        # Print incoming messages to the console
        print(f'{message.author.name}: {message.content}')

        # Search for the pattern in the message content
        pattern = r'!next'
        match = re.search(pattern, message.content)
        if match and message.author.name in valid_users:
            print("Next song requested by valid user")

            global stop_song
            stop_song = True

        # Check for a song request
        pattern = r'!song\s+(\w+)'
        match = re.search(pattern, message.content)
        if match:
            # Extract the YouTube video ID from the matched pattern
            video_id = match.group(1)
            await download_song_request(message, video_id)

    # Take users in chat and play their songs
    async def play_song_requests(self):

        song_lock = asyncio.Lock()
        global played_songs
        global song_queue
        global stop_song

        # Change if possible dont like while true
        while True:

            # If their are songs in the queue play them now
            if len(song_queue) > 0:

                # Grab the song id from slot 0
                video_id = song_queue.pop(0)
                file_path = f"downloaded_songs/{video_id}.mp3"  

                stop_song = False

                if os.path.exists(file_path):
                    # Play the selected song
                    stop_song = False 
                    async with song_lock:
                        await play_mp3(file_path)

                    # append the list of played songs
                    played_songs.append(video_id)

                # If the song_id does not match a file in the folder
                else:
                    print(f"File '{file_path}' does not exist.")
                    cursor.execute("DELETE FROM users WHERE video_id = ?", (video_id,))
                    conn.commit()

                continue # back to the start of the loop

            # Get the channel object
            channel = self.get_channel('Stststudar')

            # Get all connected users in the chat
            connected_users = [chatter.name for chatter in channel.chatters]
            print(f'Connected users: {", ".join(connected_users)}')

            # Randomize the order of users
            random.shuffle(connected_users)

            # Check if any connected user has a song in the database
            for user in connected_users:
                print("searching user %s for current song" % (user))
                cursor.execute("SELECT video_id FROM users WHERE username = ?", (user,))
                results = cursor.fetchall()

                # if the user has songs quested inside the database
                if results:
                    video_id = random.choice(results)[0]

                    # Check if the song has been palyed all ready
                    if video_id in played_songs:
                        continue


                    # Adjust the file path based on your downloaded songs location
                    file_path = f"downloaded_songs/{video_id}.mp3"  
                    # Play the selected song

                    # Check if the file exists at the specified path
                    if os.path.exists(file_path):
                        # Play the selected song
                        stop_song = False 
                        async with song_lock:
                            await play_mp3(file_path)

                        # append the list of played songs
                        played_songs.append(video_id)

                    # If the song_id does not match a file in the folder
                    else:
                        print(f"File '{file_path}' does not exist.")
                        cursor.execute("DELETE FROM users WHERE video_id = ?", (video_id,))
                        conn.commit()

                    # If the played list is to full remove the first item
                    if len(played_songs) > num_of_songs - 1:
                        played_songs.pop(0)
                    break

            await asyncio.sleep(1)

if __name__ == "__main__":

    twitch_token = None

    # Open the file with token inside
    with open('song_bot_token.txt', 'r') as file:
        twitch_token = file.readline().strip()

    # global num_of_songs

    downloaded_songs_dir = "downloaded_songs"

    # Get the list of files in the downloaded_songs directory
    file_list = os.listdir(downloaded_songs_dir)

    # Filter the files based on their extension (.mp3)
    mp3_files = [file for file in file_list if file.endswith(".mp3")]

    # Get the number of .mp3 files
    num_of_songs = len(mp3_files)

    print(f"Number of .mp3 files: {num_of_songs}")

    '''
    # Check that the user has inputed the downloaded songs file location
    if len(sys.argv) < 2:
        print("Usage: python script.py <mp3_file>")
        sys.exit(1)

    mp3_file = sys.argv[1]
    '''

    bot = Bot(twitch_token)
    # bot.run()
    bot.run()
