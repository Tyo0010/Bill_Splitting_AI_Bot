import os
import logging
# from dotenv import load_dotenv # No longer needed for Lambda
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, TypeHandler
from PIL import Image
import asyncio
import json # Import json
import base64 # <--- Import base64

# Load environment variables from .env file
# load_dotenv()

# Update constants
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = "@Bill_Splitting_AI_Bot"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Add a variable for the webhook URL (set in Lambda env vars)
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Initialize Gemini client with updated model
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-pro-exp-03-25')

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO # Use INFO level for production
)
logger = logging.getLogger(__name__)

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

async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
# Handle cases where there might not be a photo (e.g., text message)
    if not message or not message.photo:
         logger.debug("Received update without message or photo.")
         return

    photo = message.photo[-1]
    caption = message.caption or ""
    downloaded_path = None
    
    if BOT_USERNAME not in caption:
        logger.debug(f"Bot username {BOT_USERNAME} not found in caption: '{caption}'. Ignoring message.")
        return # Exit if the bot wasn't mentioned

    
    try:
        # Extract participants info from caption
        participants_info = caption.replace(BOT_USERNAME, "").strip()
        
        if not participants_info:
            await message.reply_text("Please provide participant information in the caption!")
            return

        # Download photo
        photo_file = await photo.get_file()
        downloaded_path = await photo_file.download_to_drive()


        # Process with AI
        await message.reply_text("Processing receipt and calculating split...")
        try:
            split_result = await process_receipt_with_ai(downloaded_path, participants_info)
            # Fix escape sequence
            escaped_result = split_result.replace(".", r"\.")
            # Ensure result is not empty
            if not escaped_result.strip():
                escaped_result = "Could not extract split details."

            await message.reply_text(
                f"🧮 *Bill Split Results:*\n```\n{escaped_result}\n```",
                parse_mode='MarkdownV2'
            )
        except Exception as api_error:
            logger.error(f"API Error: {str(api_error)}", exc_info=True)
            await message.reply_text(
                "Sorry, there was an error processing the receipt. Please try again."
            )

    except Exception as e:
        logger.error(f"Error in handle_receipt: {str(e)}", exc_info=True)
        await message.reply_text(
            "Sorry, an error occurred. Please make sure:\n"
            "1. The image is clear and readable\n"
            "2. The caption format is correct\n"
            "3. Try again or contact support if the issue persists"
        )
    finally:
        # Cleanup downloaded file
        if downloaded_path and os.path.exists(downloaded_path):
            try:
                os.remove(downloaded_path)
                logger.debug(f"Cleaned up temporary file: {downloaded_path}")
            except Exception as cleanup_error:
                logger.error(f"Error cleaning up file: {cleanup_error}")

async def process_receipt_with_ai(image_path: str, participants_info: str) -> str:
    try:
        # Load and process image
        image = Image.open(image_path)
        
        # Prepare prompt with more specific instructions
        prompt = f"""
        Analyze this receipt image and calculate the bill split based on the following orders:
        {participants_info}
        pay attention to quantities and prices. Be careful, some items can be shared between people. Return only final split results
        """

        response = model.generate_content(
            [prompt, image],
        )

        return response.text.strip()

    except Exception as e:
        logger.error(f"Error in process_receipt_with_ai: {str(e)}", exc_info=True)
        raise # Re-raise the exception to be caught in handle_receipt


# --- Initialize the application (outside the handler) ---
application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
# Use TypeHandler for general updates, including photos with captions
application.add_handler(TypeHandler(Update, handle_receipt)) # Simplified handler


# --- Lambda Handler Function ---
async def lambda_handler_async(event, context):
    """AWS Lambda handler function."""
    try:
        # --- Log the raw event first for debugging ---
        # Be mindful this might log sensitive info if the body contains it,
        # but it's crucial for debugging the event structure.
        logger.info(f"Received raw event: {event}")
        logger.info(f"Received event type: {type(event)}")
        if isinstance(event, dict):
            logger.info(f"Event keys: {list(event.keys())}")

        await application.initialize() # Initialize handlers

        # --- Simplified and Corrected Body Handling ---
        body_content = event.get("body")
        is_base64 = event.get("isBase64Encoded", True)
        data = None # Variable to hold the final parsed JSON data

        if body_content is None:
            logger.error("Event body is missing.")
            return {'statusCode': 400, 'body': 'Missing body'}

        if not isinstance(body_content, str):
            # If the body is somehow already a dict (less likely with proxy integration)
            if isinstance(body_content, dict):
                 logger.warning("Event body was already a dict, using directly.")
                 data = body_content
            else:
                logger.error(f"Unexpected event body type: {type(body_content)}")
                return {'statusCode': 400, 'body': 'Unexpected body format'}
        else:
            # Body is a string, decode if necessary
            body_str = body_content
            if is_base64:
                logger.info("Body is Base64 encoded, decoding...")
                try:
                    decoded_bytes = base64.b64decode(body_str)
                    body_str = decoded_bytes.decode('utf-8') # Decode bytes to string
                    logger.info("Successfully decoded Base64 body.")
                except (base64.binascii.Error, UnicodeDecodeError) as b64_err:
                    logger.error(f"Failed to decode Base64 body: {b64_err}")
                    return {'statusCode': 400, 'body': 'Invalid Base64 encoding'}
            else:
                 logger.info("Body is not Base64 encoded.")

            # Now parse the JSON string (either original or decoded)
            if not body_str:
                 logger.error("Body string is empty after potential decoding.")
                 return {'statusCode': 400, 'body': 'Empty body string'}

            try:
                data = json.loads(body_str)
                logger.info("Successfully parsed JSON from body string.")
            except json.JSONDecodeError as json_err:
                logger.error(f"Failed to parse JSON from body string: {json_err}")
                logger.error(f"Body string was: {body_str[:500]}") # Log beginning of string
                return {'statusCode': 400, 'body': 'Invalid JSON body'}

        # --- End Simplified Body Handling ---

        if not data:
             # This check might be redundant now but kept for safety
            logger.error("Could not extract data from event body.")
            return {'statusCode': 400, 'body': 'Empty or invalid data'}

        # Log the keys of the extracted data to confirm update_id presence
        logger.info(f"Data keys for Update.de_json: {list(data.keys())}")

        # Check if update_id is present before deserializing
        if 'update_id' not in data:
            logger.error(f"Missing 'update_id' in data: {data}")
            return {'statusCode': 400, 'body': "Missing 'update_id' in request data"}

        update = Update.de_json(data=data, bot=application.bot)
        await application.process_update(update)

        logger.info("Update processed successfully")
        return {
            'statusCode': 200,
            'body': 'Update processed'
        }
    except Exception as e:
        logger.error(f"Error processing update in Lambda: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': 'Error processing update'
        }

# --- Wrapper for Lambda runtime ---
def lambda_handler(event, context):
    """Synchronous wrapper for the async handler."""
    # Use asyncio.run() in Python 3.7+ for cleaner event loop management
    return asyncio.run(lambda_handler_async(event, context))

# --- Optional: Function to set the webhook (run once locally or via Lambda invoke) ---
async def set_webhook():
    if not WEBHOOK_URL:
        logger.error("WEBHOOK_URL environment variable not set.")
        return
    await application.initialize()
    await application.bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"Webhook set to {WEBHOOK_URL}")

# --- Remove the old main() polling logic ---
# def main() -> None:

#     application = Application.builder().token(BOT_TOKEN).build()

#     application.add_handler(CommandHandler("start", start))
#     application.add_handler(CommandHandler("help", help_command))


#     application.add_handler(MessageHandler(
#         filters.PHOTO & (filters.COMMAND | filters.ChatType.GROUPS | filters.ChatType.PRIVATE), 
#         handle_receipt
#     ))

#     logger.info("Starting bot...")
#     application.run_polling(allowed_updates=Update.ALL_TYPES)

# if __name__ == '__main__':
#     main()