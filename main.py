import os
import logging
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, TypeHandler
from PIL import Image
import asyncio
import json
import base64
import binascii
from flask import Flask, request, Response # Import Flask components

# --- Environment Variables & Constants ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN set for Flask application")
BOT_USERNAME = "@Bill_Splitting_AI_Bot" # Keep or fetch dynamically if needed
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# WEBHOOK_URL is usually set by Telegram, not needed directly in the code here

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Gemini AI Setup ---
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-pro-exp-03-25')
else:
    logger.warning("GEMINI_API_KEY not found. AI processing will fail.")
    model = None # Handle cases where the model might not be available

# --- Telegram Bot Setup ---
# Initialize the Application outside the request context for efficiency
ptb_app = Application.builder().token(BOT_TOKEN).build()

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
        logger.info("Received update without message or photo.")
        # Optionally reply if it's a direct message or mention without photo
        # await message.reply_text("Please send a photo with a caption.")
        return

    photo = message.photo[-1]
    caption = message.caption or ""
    downloaded_path = None

    if BOT_USERNAME not in caption:
        logger.info(f"Bot username {BOT_USERNAME} not found in caption: '{caption}'. Ignoring.")
        return

    if not model:
         await message.reply_text("AI Model is not configured. Cannot process receipt.")
         return

    try:
        participants_info = caption.replace(BOT_USERNAME, "").strip()
        if not participants_info:
            await message.reply_text("Please provide participant information in the caption!")
            return

        await message.reply_text("Processing receipt and calculating split...")
        photo_file = await photo.get_file()
        # Note: download_to_drive might not work reliably in Lambda's ephemeral storage.
        # Consider downloading to memory (BytesIO) if issues arise.
        downloaded_path = await photo_file.download_to_drive()

        split_result = await process_receipt_with_ai(downloaded_path, participants_info)
        escaped_result = split_result.replace(".", r"\.") # For MarkdownV2
        if not escaped_result.strip():
            escaped_result = "Could not extract split details."

        await message.reply_text(
            f"🧮 *Bill Split Results:*\n```\n{escaped_result}\n```",
            parse_mode='MarkdownV2'
        )

    except Exception as e:
        logger.error(f"Error in handle_receipt: {str(e)}", exc_info=True)
        await message.reply_text(
            "Sorry, an error occurred processing the receipt. Please check the image and caption format."
        )
    finally:
        if downloaded_path and os.path.exists(downloaded_path):
            try:
                os.remove(downloaded_path)
                logger.info(f"Cleaned up temporary file: {downloaded_path}")
            except Exception as cleanup_error:
                logger.error(f"Error cleaning up file: {cleanup_error}")

async def process_receipt_with_ai(image_path: str, participants_info: str) -> str:
    if not model:
        raise ValueError("Gemini AI model not initialized.")
    try:
        image = Image.open(image_path)
        prompt = f"""
        Analyze this receipt image and calculate the bill split based on the following orders:
        {participants_info}
        Pay attention to quantities and prices. Be careful, some items can be shared between people.
        Return only the final split results per person in a clear, itemized format.
        Example:
        Alice owes: $XX.XX (burger $Y.YY, coke $Z.ZZ)
        Bob owes: $AA.AA (pasta $B.BB, salad $C.CC)
        """
        response = await model.generate_content_async([prompt, image]) # Use async version if available/preferred
        return response.text.strip()
    except Exception as e:
        logger.error(f"Error in process_receipt_with_ai: {str(e)}", exc_info=True)
        raise

# --- Register Handlers with PTB Application ---
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CommandHandler("help", help_command))
# Use MessageHandler to specifically catch photos with captions mentioning the bot
ptb_app.add_handler(MessageHandler(
    filters.PHOTO & filters.CaptionRegex(BOT_USERNAME) & (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP),
    handle_receipt
))
# Optional: Add a handler for private chats if needed
# ptb_app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(BOT_USERNAME) & filters.ChatType.PRIVATE, handle_receipt))


# --- Flask Application ---
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
async def webhook():
    """Webhook endpoint to receive updates from Telegram."""
    logger.info("Webhook received a request.")
    if request.content_type != 'application/json':
        logger.warning(f"Invalid content type: {request.content_type}")
        return Response(status=403) # Forbidden

    try:
        update_data = request.get_json(force=True)
        logger.debug(f"Received update data: {update_data}")

        # Ensure the application is initialized (usually done above)
        await ptb_app.initialize()
        if not ptb_app.bot:
             logger.error("PTB application bot instance is None.")
             return Response("Bot initialization failed", status=500)

        update = Update.de_json(update_data, ptb_app.bot)
        logger.info(f"Processing update: {update.update_id}")

        # Process the update using the PTB application's handlers
        await ptb_app.process_update(update)

        # Return 200 OK to Telegram
        return Response(status=200)

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON: {e}", exc_info=True)
        return Response("Invalid JSON received", status=400)
    except Exception as e:
        logger.error(f"Error processing update in webhook: {e}", exc_info=True)
        return Response("Error processing update", status=500)

# --- Remove the old lambda_handler and main() polling logic ---

# Optional: Add for local development testing (not used by Zappa)
# if __name__ == '__main__':
#     # Note: Running locally this way won't receive webhooks unless you use ngrok or similar
#     # and manually set the webhook URL with Telegram.
#     # It's primarily for syntax checking or testing specific functions.
#     # For full local testing, consider running PTB's polling mode temporarily.
#     app.run(debug=True, port=5000)