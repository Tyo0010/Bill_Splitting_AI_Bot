import asyncio
# --- Try setting uvloop policy ---
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    print("Using uvloop event loop policy.")
except ImportError:
    print("uvloop not found, using default asyncio event loop policy.")
# --- End uvloop policy setting ---

import os
import logging
import google.generativeai as genai
from telegram import Update
# Import Bot separately if needed in set_webhook
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, TypeHandler
from PIL import Image
# import asyncio # Already imported above
import json
import io # <--- Add this import
import base64
import binascii
from dotenv import load_dotenv
from flask import Flask, request, Response # Import Flask components

load_dotenv()  # Load environment variables from .env file

# --- Environment Variables & Constants ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN set for Flask application")
BOT_USERNAME = "@Bill_Splitting_AI_Bot" # Keep or fetch dynamically if needed
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# --- Add WEBHOOK_URL ---
WEBHOOK_URL = os.getenv("WEBHOOK_URL") # e.g., https://your-api-gateway-id.execute-api.region.amazonaws.com/main
logger = logging.getLogger(__name__)
if not WEBHOOK_URL:
    logger.warning("WEBHOOK_URL not set. /setwebhook route will not function correctly.")
# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- Gemini AI Setup ---
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-pro-exp-03-25')
else:
    logger.warning("GEMINI_API_KEY not found. AI processing will fail.")
    model = None # Handle cases where the model might not be available

# --- Telegram Bot Setup ---
# Initialize the Application outside the request context for efficiency


# --- Bot Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Hi! Add me to a group, then tag me ({BOT_USERNAME}) in a message with a receipt photo to split the bill.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "How to use:\n"
        "1. Add me to your group.\n"
        "2. Take a clear photo of your receipt.\n"
        "3. Send the photo to the group with caption in this format:\n\n"
        f"{BOT_USERNAME}\n"
        "Person1: item1, item2\n"
        "Person2: item1, item2\n\n"
        "Example:\n"
        f"{BOT_USERNAME}\n"
        "Alice: burger, coke\n"
        "Bob: pasta, salad\n\n"
        "Commands:\n"
        "/start - Welcome message\n"
        "/help - This message"
    )

# --- Receipt Handling Logic ---
async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.photo:
        print("Received update without message or photo.")
        # Optionally reply if it's a direct message or mention without photo
        # await message.reply_text("Please send a photo with a caption.")
        return

    photo = message.photo[-1]
    caption = message.caption or ""
    image_bytes = None # Use bytes instead of path

    if BOT_USERNAME not in caption:
        print(f"Bot username {BOT_USERNAME} not found in caption: '{caption}'. Ignoring.")
        return

    if not model:
         await message.reply_text("AI Model is not configured. Cannot process receipt.")
         return

    try:
        participants_info = caption.replace(BOT_USERNAME, "").strip()
        if not participants_info:
            await message.reply_text("Please provide participant information in the caption!")
            return

        print("Sending 'Processing...' message.")
        await message.reply_text("Processing receipt and calculating split...")

        print("Getting photo file object...")
        photo_file = await photo.get_file()
        print(f"Got photo file object: {photo_file.file_id}")

        # Download photo to memory (BytesIO)
        print("Downloading photo to memory...")
        image_stream = io.BytesIO()
        await photo_file.download_to_memory(image_stream)
        image_stream.seek(0) # Reset stream position
        print("Photo downloaded to memory.")

        print("Calling process_receipt_with_ai...")
        split_result = await process_receipt_with_ai(image_stream, participants_info)
        print("Received result from AI.")

        escaped_result = split_result.replace(".", r"\.") # For MarkdownV2
        if not escaped_result.strip():
            escaped_result = "Could not extract split details."
        print("Sending final result message...")
        await message.reply_text(
            f"🧮 *Bill Split Results:*\n```\n{escaped_result}\n```",
            parse_mode='MarkdownV2'
        )

    except Exception as e:
        logger.error(f"Error in handle_receipt: {str(e)}", exc_info=True)
        await message.reply_text(
            "Sorry, an error occurred processing the receipt. Please check the image and caption format."
        )
    # No finally block needed for file cleanup when using BytesIO

async def process_receipt_with_ai(image_stream: io.BytesIO, participants_info: str) -> str:
    if not model:
        raise ValueError("Gemini AI model not initialized.")
    try:
        # Open image directly from the BytesIO stream
        image = Image.open(image_stream)
        prompt = f"""
        You are an expert receipt analyzing AI.
        Analyze this receipt image and calculate the bill split based on the following orders:
        {participants_info}
        Pay attention to quantities and prices. Be careful, some items can be shared between people.
        Return only final split results
        """
        # Make sure generate_content_async is the correct method name for your version
        response = await model.generate_content_async([prompt, image])
        return response.text.strip()
    except Exception as e:
        logger.error(f"Error in process_receipt_with_ai: {str(e)}", exc_info=True)
        # Re-raise the exception so it's caught by handle_receipt's handler
        raise


# Optional: Add a handler for private chats if needed
# ptb_app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(BOT_USERNAME) & filters.ChatType.PRIVATE, handle_receipt))


# --- Flask Application ---
app = Flask(__name__)

ptb_app = Application.builder().token(BOT_TOKEN).build()
    # --- Register Handlers with PTB Application ---
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CommandHandler("help", help_command))
    # Use MessageHandler to specifically catch photos with captions mentioning the bot
ptb_app.add_handler(MessageHandler(
    filters.PHOTO & filters.CaptionRegex(BOT_USERNAME) & (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP),
    handle_receipt
))
@app.route('/webhook', methods=['POST'])
def webhook(): # Changed to synchronous def
    """Webhook endpoint to receive updates from Telegram. Uses asyncio.run for PTB."""
    print("Webhook received a request.")
    if request.content_type != 'application/json':
        logger.warning(f"Invalid content type: {request.content_type}")
        return Response(status=403) # Forbidden

    try:
        update_data = request.get_json(force=True)
        print(f"Received update data: {update_data}")

        # --- Use asyncio.run to handle the async PTB processing ---
        async def process():
            # Let PTB handle initialization lazily if needed
            # await ptb_app.initialize() # Removed explicit initialize again

            update = Update.de_json(update_data, ptb_app.bot)
            print(f"Processing update: {update.update_id}")
            await ptb_app.process_update(update)

        # --- Explicitly create and manage a new event loop ---
        loop = asyncio.new_event_loop()
        # asyncio.set_event_loop(loop) # <-- Remove this line
        try:
            loop.run_until_complete(process()) # Run directly on the loop object
        finally:
            # Ensure the loop is closed even if errors occur in process()
            loop.close()
        # --- End explicit loop management ---

        # Return 200 OK to Telegram
        return Response(status=200)

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON: {e}", exc_info=True)
        return Response("Invalid JSON received", status=400)
    except Exception as e:
        logger.error(f"Error processing update in webhook: {e}", exc_info=True)
        return Response("Error processing update", status=500)

# --- Add /setwebhook route from template concept ---
@app.route('/setwebhook', methods=['GET', 'POST'])
def set_telegram_webhook(): # Changed to synchronous def
    """Sets the Telegram webhook URL. Uses asyncio.run for PTB."""
    from telegram import Bot # Import Bot locally for this function
    if not WEBHOOK_URL:
        return "Webhook URL not configured in environment variables.", 500

    # Construct the full webhook URL Telegram should POST to
    full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}/webhook" # Append your webhook path
    print(f"Attempting to set webhook to: {full_webhook_url}")

    # --- Use asyncio.run to handle the async PTB call ---
    async def set_hook():
        try:
            # Create a temporary Bot instance just for this call
            temp_bot = Bot(token=BOT_TOKEN)

            await temp_bot.set_webhook(full_webhook_url)
            print(f"Webhook successfully set to {full_webhook_url}")
            return f"Webhook successfully set to {full_webhook_url}", 200
        except Exception as e:
            logger.error(f"Failed to set webhook inside set_hook: {e}", exc_info=True)
            # Re-raise or return an error indication if needed,
            # but the outer try/except will catch it if raised.
            raise # Re-raise the exception to be caught below

    try:
        # --- Explicitly create and manage a new event loop ---
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result, status_code = loop.run_until_complete(set_hook())
        finally:
            loop.close()
        return result, status_code
        # --- End explicit loop management ---
    except Exception as e:
        # Log the final error caught from asyncio.run
        logger.error(f"Failed to set webhook: {e}", exc_info=True)
        return f"Failed to set webhook: {e}", 500

# --- Add index route from template concept ---
@app.route('/', methods=['GET'])
def index():
    """Basic index route for health check or verification."""
    return "Flask server is running.", 200

# --- Remove the old lambda_handler and main() polling logic ---

# Optional: Add for local development testing (not used by Zappa)
# if __name__ == '__main__':
#     # Note: Running locally this way won't receive webhooks unless you use ngrok or similar
#     # and manually set the webhook URL with Telegram.
#     # It's primarily for syntax checking or testing specific functions.
#     # For full local testing, consider running PTB's polling mode temporarily.
#     app.run(debug=True, port=5000)