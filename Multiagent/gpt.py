# Interaction with AI assistants.
from datetime import datetime
import random, json, shutil
from pathlib import Path
from io import BytesIO
import os
import base64

from loguru import logger
from openai import AsyncOpenAI

_openai_client = None


def _init_ai_once():
    global _openai_client
    if _openai_client is None:
        print("Initializing openai.AsyncOpenAI")
        _openai_client = AsyncOpenAI()


async def gpt_get_answer(messages, temperature=0.5, model="gpt-4-turbo"): #model="gpt-4-0125-preview"):
    """
    Gets the answer given a list of messages.

    Parameters:
      messages: List of dicts that represents chronlogical order.
        'role': Common roles:
           'user': 'From the user's perspective.'
           'agent': customer service/support role.
           'assistant': ChatGPT, etc.
           'system': Automated notifications.
           'moderator': For a moderator who keeps the peace.
           'admin': For a server admin.
        'content': The message string itself.
        'user_id': Who spoke.
      temperature=0.5: How much randomness the AI's thoughts have.
      model="gpt-4": The model type.
    """
    _init_ai_once()

    try:
        completion = await _openai_client.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=messages
        )
        return completion.choices[0].message.content
    except Exception as e:
        logger.error(e)
        raise e
