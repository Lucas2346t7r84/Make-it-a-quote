import io
import os
import re
import aiohttp
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

# --- DUMMY WEB SERVER FOR RENDER ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

def run_web_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()
# -----------------------------------

intents = discord.Intents.default()
intents.message_content = True

class QuoteBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Commands synced successfully!")

bot = QuoteBot()

def generate_quote_card(text: str, server_name: str, username: str, avatar_bytes: bytes = None, media_bytes: bytes = None) -> io.BytesIO:
    width = 800
    height = 450  # Fixed clean card height
    background_color = (15, 15, 15)
    text_color = (240, 240, 240)
    meta_color = (160, 160, 160)

    # Load fonts
    try:
        font_quote = ImageFont.truetype("arial.ttf", 32)
        font_meta = ImageFont.truetype("arial.ttf", 18)
    except IOError:
        font_quote = ImageFont.load_default()
        font_meta = ImageFont.load_default()

    # Create base image
    img = Image.new("RGB", (width, height), color=background_color)
    draw = ImageDraw.Draw(img)

    # 1. Paste user avatar on the left with a smooth horizontal fade mask
    if avatar_bytes:
        try:
            avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar_img = avatar_img.resize((height, height))
            
            # Create horizontal alpha gradient mask for smooth fade in the middle
            mask = Image.new("L", (height, height), 0)
            mask_draw = ImageDraw.Draw(mask)
            fade_start = int(height * 0.4)
            fade_end = int(height * 0.85)
            
            for x in range(height):
                if x < fade_start:
                    alpha = 255
                elif x > fade_end:
                    alpha = 0
                else:
                    alpha = int(255 * (1.0 - (x - fade_start) / (fade_end - fade_start)))
                mask_draw.line([(x, 0), (x, height)], fill=alpha)
                
            avatar_img.putalpha(mask)
            img.paste(avatar_img, (0, 0), avatar_img)
        except Exception as e:
            print(f"Error loading avatar: {e}")

    # 2. Right side text layout parameters
    right_start_x = 380
    right_width = 390
    center_x = right_start_x + (right_width // 2)

    # Wrap quote text to fit the right side box
    lines = []
    if text:
        max_chars_per_line = 22  # Optimized for size 32 font
        words = text.split(' ')
        current_line = ""
        for word in words:
            if len(current_line + " " + word) <= max_chars_per_line:
                current_line += (" " if current_line else "") + word
            else:
                lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

    formatted_lines = [f'"{lines[0]}'] + lines[1:-1] + [f'{lines[-1]}"'] if len(lines) > 1 else ([f'"{lines[0]}"'] if lines else [])

    # Draw Centered Quote Lines
    current_y = 50
    line_spacing = 40
    if formatted_lines:
        for line in formatted_lines:
            # Measure line width for precise centering
            bbox = draw.textbbox((0, 0), line, font=font_quote)
            line_w = bbox[2] - bbox[0]
            line_x = center_x - (line_w // 2)
            draw.text((line_x, current_y), line, fill=text_color, font=font_quote)
            current_y += line_spacing

    # Handle Media (Images, Stickers, GIFs if present)
    if media_bytes:
        try:
            media_img = Image.open(io.BytesIO(media_bytes))
            if hasattr(media_img, "is_animated") and media_img.is_animated:
                media_img.seek(0)
            media_img = media_img.convert("RGB")
            media_img.thumbnail((260, 140))
            media_x = center_x - (media_img.width // 2)
            img.paste(media_img, (media_x, current_y + 10))
            current_y += media_img.height + 20
        except Exception as e:
            print(f"Error loading media: {e}")

    # 3. Draw -Server Name and @username below (Centered)
    current_y = max(current_y + 15, 320)  # Ensure proper spacing near bottom
    
    server_text = f"- {server_name}"
    bbox_s = draw.textbbox((0, 0), server_text, font=font_meta)
    sx = center_x - ((bbox_s[2] - bbox_s[0]) // 2)
    draw.text((sx, current_y), server_text, fill=meta_color, font=font_meta)
    
    current_y += 24
    user_text = f"{username}"
    bbox_u = draw.textbbox((0, 0), user_text, font=font_meta)
    ux = center_x - ((bbox_u[2] - bbox_u[0]) // 2)
    draw.text((ux, current_y), user_text, fill=meta_color, font=font_meta)

    # Save to buffer
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")

# Context Menu Command (Right-click -> Apps -> Make it a Quote)
@bot.tree.context_menu(name="Make it a Quote")
async def quote_context(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer()

    avatar_bytes = None
    if message.author.display_avatar:
        avatar_bytes = await message.author.display_avatar.with_format("png").read()

    clean_text = re.sub(r'https?://\S+', '', message.content).strip()
    server_name = message.guild.name if message.guild else "Direct Message"
    username = f"@{message.author.name}"

    media_bytes = None
    async with aiohttp.ClientSession() as session:
        if message.attachments:
            attachment = message.attachments[0]
            if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.apng']):
                async with session.get(attachment.url) as resp:
                    if resp.status == 200:
                        media_bytes = await resp.read()

        if not media_bytes and message.stickers:
            sticker = message.stickers[0]
            async with session.get(sticker.url) as resp:
                if resp.status == 200:
                    media_bytes = await resp.read()

        if not media_bytes and message.embeds:
            for embed in message.embeds:
                target_url = embed.image.url or embed.thumbnail.url or (embed.video.url if embed.video else None)
                if target_url:
                    async with session.get(target_url) as resp:
                        if resp.status == 200:
                            media_bytes = await resp.read()
                            break

    buffer = generate_quote_card(
        text=clean_text,
        server_name=server_name,
        username=username,
        avatar_bytes=avatar_bytes,
        media_bytes=media_bytes
    )

    file = discord.File(fp=buffer, filename="quote.png")
    await interaction.followup.send(file=file)

# Slash Command (/quote)
@bot.tree.command(name="quote", description="Quote a specific text manually")
@app_commands.describe(text="The message to quote", author="Who said it (optional)")
async def quote_slash(interaction: discord.Interaction, text: str, author: discord.User = None):
    await interaction.response.defer()

    target_user = author or interaction.user
    avatar_bytes = None
    if target_user.display_avatar:
        avatar_bytes = await target_user.display_avatar.with_format("png").read()

    server_name = interaction.guild.name if interaction.guild else "Direct Message"
    username = f"@{target_user.name}"

    buffer = generate_quote_card(
        text=text,
        server_name=server_name,
        username=username,
        avatar_bytes=avatar_bytes
    )

    file = discord.File(fp=buffer, filename="quote.png")
    await interaction.followup.send(file=file)

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    bot.run(TOKEN)
