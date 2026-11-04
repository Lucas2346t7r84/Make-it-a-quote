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

class OriginalMessageView(discord.ui.View):
    def __init__(self, jump_url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Go to Original Text", style=discord.ButtonStyle.link, url=jump_url))

def generate_quote_card(text: str, username: str, avatar_bytes: bytes = None, media_bytes: bytes = None) -> io.BytesIO:
    width = 900
    height = 500
    background_color = (15, 15, 15)
    text_color = (245, 245, 245)
    meta_color = (180, 180, 180)

    # Right-side safe bounding box boundaries
    box_x_start = 420
    box_width = 440
    box_center_x = box_x_start + (box_width // 2)

    # Dynamically select font size based on text length to ensure it always fits
    text_len = len(text)
    if text_len < 15:
        font_size = 52
        max_chars_per_line = 12
    elif text_len < 40:
        font_size = 40
        max_chars_per_line = 16
    elif text_len < 90:
        font_size = 30
        max_chars_per_line = 22
    else:
        font_size = 22
        max_chars_per_line = 32

    # Load Linux-compatible system fonts
    font_path_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_path_reg = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    
    try:
        font_quote = ImageFont.truetype(font_path_bold, font_size)
        font_user = ImageFont.truetype(font_path_bold, 22)
    except IOError:
        try:
            font_quote = ImageFont.truetype("arialbd.ttf", font_size)
            font_user = ImageFont.truetype("arialbd.ttf", 22)
        except IOError:
            font_quote = ImageFont.load_default()
            font_user = ImageFont.load_default()

    # Create base image
    img = Image.new("RGB", (width, height), color=background_color)
    draw = ImageDraw.Draw(img)

    # 1. Paste user avatar on the left with a smooth horizontal fade mask
    if avatar_bytes:
        try:
            avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar_img = avatar_img.resize((height, height))
            
            mask = Image.new("L", (height, height), 0)
            mask_draw = ImageDraw.Draw(mask)
            fade_start = int(height * 0.40)
            fade_end = int(height * 0.75)
            
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

    # Wrap quote text cleanly
    lines = []
    if text:
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

    # Calculate vertical layout spacing
    line_spacing = int(font_size * 1.25)
    total_text_height = len(formatted_lines) * line_spacing
    
    # Draw Centered Quote Lines
    current_y = max(40, (380 - total_text_height) // 2)
    if formatted_lines:
        for line in formatted_lines:
            bbox = draw.textbbox((0, 0), line, font=font_quote)
            line_w = bbox[2] - bbox[0]
            line_x = box_center_x - (line_w // 2)
            draw.text((line_x, current_y), line, fill=text_color, font=font_quote)
            current_y += line_spacing

    # Handle Media if present
    if media_bytes:
        try:
            media_img = Image.open(io.BytesIO(media_bytes))
            if hasattr(media_img, "is_animated") and media_img.is_animated:
                media_img.seek(0)
            media_img = media_img.convert("RGB")
            media_img.thumbnail((240, 100))
            media_x = box_center_x - (media_img.width // 2)
            img.paste(media_img, (media_x, current_y + 5))
        except Exception as e:
            print(f"Error loading media: {e}")

    # 2. Draw larger @username near bottom center
    username_y = 420
    bbox_u = draw.textbbox((0, 0), username, font=font_user)
    ux = box_center_x - ((bbox_u[2] - bbox_u[0]) // 2)
    draw.text((ux, username_y), username, fill=meta_color, font=font_user)

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
        username=username,
        avatar_bytes=avatar_bytes,
        media_bytes=media_bytes
    )

    file = discord.File(fp=buffer, filename="quote.png")
    view = OriginalMessageView(jump_url=message.jump_url)
    await interaction.followup.send(file=file, view=view)

# Slash Command (/quote)
@bot.tree.command(name="quote", description="Quote a specific text manually")
@app_commands.describe(text="The message to quote", author="Who said it (optional)")
async def quote_slash(interaction: discord.Interaction, text: str, author: discord.User = None):
    await interaction.response.defer()

    target_user = author or interaction.user
    avatar_bytes = None
    if target_user.display_avatar:
        avatar_bytes = await target_user.display_avatar.with_format("png").read()

    username = f"@{target_user.name}"

    buffer = generate_quote_card(
        text=text,
        username=username,
        avatar_bytes=avatar_bytes
    )

    file = discord.File(fp=buffer, filename="quote.png")
    # For manual slash command quotes without a source message link, we don't attach the link button
    await interaction.followup.send(file=file)

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    bot.run(TOKEN)
