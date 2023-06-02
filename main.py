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
played_songs = []  # List to track the songs that have been played
num_of_songs = 0
song_queue = []
current_song = None
song_to_delete = None
download_location = "downloaded_songs"
file_lock = asyncio.Lock()

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

# Create the 'banned_songs' table if it doesn't exist
cursor.execute("CREATE TABLE IF NOT EXISTS banned_songs (video_id TEXT PRIMARY KEY, user TEXT)")

# Play the current song
async def play_mp3(file_path):

    pygame.mixer.init()
    pygame.mixer.music.load(file_path)
    pygame.mixer.music.play()
    
    global stop_song
    stop_song = False

    print(f"Starting song\n{file_path}")

    while pygame.mixer.music.get_busy() and not stop_song:
        await asyncio.sleep(1)
        # continue

    # Stop the song if it's still playing
    pygame.mixer.music.stop()

# Ban a song
async def ban_song(ban_song_id=None):
    global current_song
    global played_songs

    # Ban the current song
    if ban_song_id is None:
        ban_song_id = song_to_delete 

    # Find the user who submited the song
    cursor.execute("SELECT username FROM users WHERE video_id = ?", (ban_song_id,))
    result = cursor.fetchone()
    username = None
    if result:
        username = result[0]

    print("################################################")
    print(f"Banning song from user: {username}")
    print("################################################")

    # Insert ban song id into db
    cursor.execute("INSERT INTO banned_songs (video_id, user) VALUES (?, ?)", (ban_song_id, username))
    conn.commit()

    # Remove from user requests
    cursor.execute("DELETE FROM users WHERE video_id = ?", (ban_song_id,))
    conn.commit()

    # Create the file path to the ban song
    global download_location
    file_path = os.path.join(download_location, f"{ban_song_id}.mp3")

    # Remove song from playlist so it does not overflow
    if ban_song_id in played_songs:
        played_songs.remove(ban_song_id)

    # Remove the song if it still exists
    print("Deleting song:", file_path)
    if os.path.exists(file_path):
        os.remove(file_path)

# Download the song as an MP3 based on code
async def download_video_as_mp3(video_code):
    global download_location

    url = "https://www.youtube.com/watch?v={}".format(video_code)
    file_name = "{}.mp3".format(video_code)
    output_path = os.path.join(download_location, file_name)  # Construct the output path

    # Check if the song is banned
    cursor.execute("SELECT video_id FROM banned_songs WHERE video_id = ?", (video_code,))
    result = cursor.fetchone()
    if result:
        print("Song is banned. Skipping download.")
        return None

    print("Downloading", file_name)
    yt = YouTube(url)
    duration = yt.length

    if duration < 360:
        # Download the youtube song to drive
        audio_stream = yt.streams.filter(only_audio=True).first()
        audio_file = audio_stream.download()
        audio = AudioSegment.from_file(audio_file)
        audio.export(output_path, format="mp3")
        # Remove the .mp4 version of the file
        os.remove(audio_file)

    print("Download Finished")
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

    # Check if the song is banned
    cursor.execute("SELECT video_id FROM banned_songs WHERE video_id = ?", (video_id,))
    result = cursor.fetchone()
    if result:
        print("#############################################################")
        print("%s Attempted to download banned song" % (message.author.name))
        print("#############################################################")
        return 

    # Check if the video ID has already been downloaded
    cursor.execute("SELECT video_id FROM downloads WHERE video_id = ?", (video_id,))
    result = cursor.fetchone()

    if result:
        # Video has already been downloaded, link user to the video ID
        cursor.execute("INSERT INTO users (username, video_id) VALUES (?, ?)", (message.author.name, video_id))
        print("Song downloaded already")
    else:
        # Download the song based on the video ID
        output_path = await download_video_as_mp3(video_id)

        if output_path is not None:
            # Insert the video ID into the downloads table
            cursor.execute("INSERT INTO downloads (video_id) VALUES (?)", (video_id,))
            # Link the user to the downloaded video ID
            cursor.execute("INSERT INTO users (username, video_id) VALUES (?, ?)", (message.author.name, video_id))
            # Add the songg to the queue
            global song_queue
            song_queue.append(video_id)
            
        # Commit the changes to the database
        conn.commit()

class Bot(twitchio.Client):
    def __init__(self, twitch_token):
        # Set up TwitchIO client
        super().__init__(token=twitch_token, initial_channels=['Stststudar'])

    async def event_ready(self):
        print(f'Logged in as {self.nick}')
        self.loop.create_task(self.play_song_requests())

    async def event_message(self, message):

        global stop_song
        global current_song
        global song_to_delete

        # Print incoming messages to the console
        print(f'{message.author.name}: {message.content}')

        # Search for the pattern in the message content
        pattern = r'!next'
        match = re.search(pattern, message.content)
        if match and message.author.name in valid_users:
            print("Next song requested by valid user")
            stop_song = True

        # Search for the pattern in the message content
        pattern = r'!ban_song'
        match = re.search(pattern, message.content)
        if match and message.author.name in valid_users:
            print("Banning current song")
            song_to_delete = current_song
            stop_song = True
            await asyncio.sleep(2)
            await ban_song()

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
        global download_location
        global current_song
        global played_songs
        global song_queue
        global stop_song

        # Always have a song playing 
        while True:

            # If there is a song in quee pick it for the video_id
            if len(song_queue) > 0:
                video_id = song_queue.pop(0)
            else: # Pick a song from user in chat

                # Pull all chatters inside a channel
                channel = self.get_channel('Stststudar')
                connected_users = [chatter.name for chatter in channel.chatters]
                print(f'Connected users: {", ".join(connected_users)}')
                random.shuffle(connected_users)

                # Loop through all chatters
                for user in connected_users:
                    print("searching user %s for current song" % (user))
                    cursor.execute("SELECT video_id FROM users WHERE username = ?", (user,))
                    results = cursor.fetchall()

                    # If the user has submited songs
                    if results:

                        # Pick a random song that has not been played yet
                        random.shuffle(results)
                        video_id = None
                        print("Played songs:", played_songs)
                        for item in results:
                            if item[0] in played_songs:
                                continue
                            else:
                                video_id = item[0]
                                break

                        # If no song was found skip to next user
                        if video_id is None:
                            break

                        # Check if the file exists
                        file_path = os.path.join(download_location, f"{video_id}.mp3")
                        if os.path.exists(file_path):
                            # Check if the song is banned
                            cursor.execute("SELECT video_id FROM banned_songs WHERE video_id = ?", (video_id,))
                            result = cursor.fetchone()
                            if result:
                                print("Song is banned. Skipping playback.")
                                if os.path.exists(file_path):
                                    os.remove(file_path)
                                continue

                            # Save id as current song and start playing it
                            current_song = video_id
                            # Once song finishes add it to played songs list
                            played_songs.append(video_id)
                            async with song_lock:
                                await play_mp3(file_path)


                        # If file does not exists delete it from db
                        else:
                            print(f"File '{file_path}' does not exist.")
                            cursor.execute("DELETE FROM users WHERE video_id = ?", (video_id,))
                            conn.commit()

                        # Get the list of files in the downloaded_songs directory
                        file_list = os.listdir(download_location)
                        # Filter the files based on their extension (.mp3)
                        mp3_files = [file for file in file_list if file.endswith(".mp3")]
                        # Get the number of .mp3 files
                        num_of_songs = len(mp3_files)
                        # Remove the oldest song in the list once all other songs have been played
                        print("Number of songs:", num_of_songs)
                        if len(played_songs) > num_of_songs - 1:
                            played_songs.pop(0)
                        break

            # Sleep incase of conditions that cause fast looping
            await asyncio.sleep(1)

if __name__ == "__main__":

    twitch_token = None

    # Open the file with token inside
    with open('song_bot_token.txt', 'r') as file:
        twitch_token = file.readline().strip()

    # Set the download location for the songs
    download_location = "downloaded_songs"

    '''
    # Check that the user has inputed the downloaded songs file location
    if len(sys.argv) < 2:
        print("Usage: python script.py <mp3_file>")
        sys.exit(1)

    mp3_file = sys.argv[1]
    '''

    # If no token is found do not run bot
    if twitch_token is None:
        exit()

    # Start the bot
    bot = Bot(twitch_token)
    bot.run()
