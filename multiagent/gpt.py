# Interaction with AI assistants.
from datetime import datetime
import random, json, shutil
from pathlib import Path
from io import BytesIO
import os
import base64
from pydantic import BaseModel, EmailStr, ValidationError

from loguru import logger
from openai import AsyncOpenAI

_openai_client = None


def _init_ai_once():
    global _openai_client
    if _openai_client is None:
        api_key_name = 'OPENAI_API_KEY'
        api_key_val = os.environ.get(api_key_name)
        if not api_key_val:
            print(f"No {api_key_name} env var set")
            import tkinter as tk # Delayed import of tkinter in case it is a headless instance which does not have tkinter installed.
            from tkinter import simpledialog
            root = tk.Tk()
            root.withdraw()
            api_key_val = simpledialog.askstring("No open AI key found", "Enter your open AI key:").strip()
            if not api_key_val:
                raise Exception('Input cancelled by user.')
        print("Initializing openai.AsyncOpenAI")
        _openai_client = AsyncOpenAI(api_key=api_key_val)


async def gpt_get_answer(messages, temperature=0.5, model="gpt-4o-mini", response_format=None): #["gpt-4-turbo", "gpt-4-0125-preview"]:
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
      response_format=None: Allows specifying a response format as a class or as a JSON object; https://platform.openai.com/docs/guides/structured-outputs/how-to-use
    """
    _init_ai_once()

    kwargs = dict(model=model, temperature=temperature, messages=messages)
    if response_format:
        kwargs['response_format'] = response_format
    try:
        completion = await _openai_client.chat.completions.create(model=model, temperature=temperature, messages=messages)
        return completion.choices[0].message.content
    except Exception as e:
        logger.error(e)
        raise e


class Person(BaseModel):
    name: str
    personality: str
class Persons(BaseModel):
    persons: list[Person]
class Place(BaseModel):
    name: str
    description: str
class Places(BaseModel):
    places: list[Place]


async def gpt_make_people(description, temperature=0.5, model="gpt-4o-mini", num=8):
    """Makes people. Returns a dict from name to personality."""
    prompt = f"""You are generating {num} persons, each with a name and personality. Please use the following description to generate your list."""
    messages=[{"role": "system", "content": prompt},
                {"role": "user", "content": description}]
    persons = gpt_get_answer(messages, temperature=temperature, model=model, response_format=Persons)
    out = {}
    for p in persons:
        out[p['name']] = p['personality']
    return out


async def gpt_make_places(description, temperature=0.5, model="gpt-4o-mini", num=8):
    """Makes people. Returns a dict from name to personality."""
    prompt = f"""You are generating {num} places, each with a place name and description. Please use the following description to generate your list."""
    messages=[{"role": "system", "content": prompt},
                {"role": "user", "content": description}]
    places = gpt_get_answer(messages, temperature=temperature, model=model, response_format=Places)
    out = {}
    for p in places:
        out[p['name']] = p['description']
    return out