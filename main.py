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
import binascii # <--- Import binascii for error handling

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



# --- Lambda Handler Function ---
async def lambda_handler_async(event, context, application: Application):
    """Processes the incoming Telegram update from the Lambda event."""
    try:
        # Check if the body is base64 encoded
        is_base64 = event.get("isBase64Encoded", False)
        body_str = event.get("body", "{}")
        # Log only the beginning of the raw body for brevity and security
        logger.debug(f"Received raw body (isBase64Encoded={is_base64}): {body_str[:100]}...")

        if is_base64:
            try:
                # Decode the base64 string
                decoded_bytes = base64.b64decode(body_str)
                # Decode bytes to UTF-8 string
                body_str = decoded_bytes.decode('utf-8')
                logger.debug(f"Decoded body string: {body_str}")
            except (binascii.Error, UnicodeDecodeError) as decode_error:
                # Log the specific decoding error
                logger.error(f"Error decoding base64 body: {decode_error} - Raw body started with: {event.get('body', '{}')[:100]}...", exc_info=True)
                return {'statusCode': 400, 'body': json.dumps('Invalid base64 encoding')}

        # Parse the JSON string body into a Python dictionary
        update_data = json.loads(body_str)
        logger.debug(f"Parsed update data: {update_data}")

        # Create an Update object from the dictionary
        # Ensure the application is initialized and bot is available
        await application.initialize()
        if not application.bot:
             logger.error("Application bot instance is None after initialization.")
             # Return an error if the bot object isn't ready
             return {'statusCode': 500, 'body': json.dumps('Bot initialization failed')}

        update = Update.de_json(update_data, application.bot)
        logger.info(f"Processing update: {update.update_id}")

        # Process the update using the application's handlers
        await application.process_update(update)

        # Return a 200 OK response to Telegram/API Gateway
        return {
            'statusCode': 200,
            'body': json.dumps('Update processed successfully')
        }

    except json.JSONDecodeError as e:
        # Log if JSON parsing fails *after* potential decoding
        logger.error(f"Error decoding JSON: {e} - Body after potential decode was: {body_str}", exc_info=True)
        return {'statusCode': 400, 'body': json.dumps('Invalid JSON received')}
    except Exception as e:
        logger.error(f"Error processing update in lambda_handler_async: {e}", exc_info=True)
        # Return 500 for other unexpected errors during processing
        return {
            'statusCode': 500,
            'body': json.dumps('Error processing update')
        }

# --- Wrapper for Lambda runtime ---
def lambda_handler(event, context):
    print("--------------------------------------")
    logging.info("Lambda handler invoked")
    logging.info(f"Event: {event}")
    logging.info(f"Context: {context}")
    logging.info(f"Context: {context}")
    
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(TypeHandler(Update, handle_receipt)) # Simplified handler
    
    """Synchronous wrapper for the async handler."""

    return asyncio.run(lambda_handler_async(event, context, application))


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