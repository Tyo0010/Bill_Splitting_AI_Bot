# Bill Splitting AI Bot

A Telegram bot that uses Google's Gemini AI to analyze receipt photos and split bills among participants.

## Features

- Process receipt photos using AI vision
- Split bills among multiple participants
- Support for group chats
- Easy-to-use caption format for orders

## Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/Bill_Splitting_AI_Bot.git
cd Bill_Splitting_AI_Bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
export BOT_TOKEN="your_telegram_bot_token"
export GEMINI_API_KEY="your_gemini_api_key"
```

4. Run the bot:
```bash
python app.py
```

## Usage

1. Add the bot to your Telegram group
2. Take a photo of your receipt
3. Send it with a caption in this format:
```
@Bill_Splitting_AI_Bot
Person1: item1, item2
Person2: item1, item2
```

## Requirements

- Python 3.8+
- Telegram Bot Token
- Google Gemini API Key

## License

MIT