# Open AI integration.

import requests, io
import json
from pydantic import BaseModel, EmailStr, ValidationError
from openai import AsyncOpenAI
from datetime import datetime
import os
import ics # pip install ics
from dateutil import parser
import pytz
from typing import List, Dict


################ Main functions ####################

async def get_calendar_event(message_names, message_contents, timezone='America/Los_Angeles'):
    """Uses AI to get a Dict event from a list of message names and contents (these two lists must be 1:1)."""
    client = OpenAIClient(timezone=timezone)
    description = '\n\n'.join([name+': '+txt for name, txt in zip(message_names, message_contents)])

    parsed_event = client.parse_event_description(description) # These are the three calls to the AI
    extracted_participants_raw = client.extract_participants(description)
    end_time_str = client.extract_event_end_time(description)

    start_time_str = parsed_event['when'] # No such function: client.extract_event_start_time(description)

    parsed_event['start_time'] = standardize_time(start_time_str, timezone)
    parsed_event['end_time'] = standardize_time(end_time_str, timezone)
    del parsed_event['when']

    extracted_participants = process_participants(extracted_participants_raw)
    parsed_event['bonus_participants'] = extracted_participants
    return parsed_event


async def save_event_to_nylas(calendar_evt, nylas_api_key, nylas_grant_id, nylas_calendar_id):
    """Saves a dict calendar evt to a Nylas calendar. No API used."""
    #client = OpenAIClient(timezone=timezone)
    evt = format_event_for_nylas(calendar_evt)
    client = NylasAPI(nylas_api_key, nylas_grant_id)
    client.create_event(calendar_id=nylas_calendar_id, event_data=evt)

    # Extract and process participants from the event description
    #emails, no_emails = self.event_processor.process_participants(extracted_participants_raw)


################ Non-AI support functions ####################

def standardize_time(time_str: str, timezone: str) -> int:
    """Non-ai natrual-language-ish time string processing. Parses it into Unix int time."""
    parsed_time = parser.parse(time_str, fuzzy=True)
    user_tz = pytz.timezone(timezone)
    user_time = user_tz.localize(parsed_time)
    utc_time = user_time.astimezone(pytz.utc)
    return int(utc_time.timestamp())


def process_participants(participants_json: str) -> tuple[Dict[str, str], List[str]]:
    # Processes participants JSON to extract emails and identify participants without valid emails
    try:
        data = json.loads(participants_json)
        participants = data["participants"]
        emails_dict = {}
        names_without_valid_email = []
        for participant in participants:
            name = participant["name"]
            email = participant.get("email")
            if email and EmailStr._validate(email):
                emails_dict[name] = email
            else:
                names_without_valid_email.append(name)
        return emails_dict, names_without_valid_email
    except json.JSONDecodeError:
        raise ValueError("Failed to parse JSON string")
    except Exception as e:
        raise ValueError(f"Error processing participants: {e}")


def format_event_for_humans(parsed_event):
    """Returns a human-readable event."""
    title = parsed_event['title']
    participants = [(p['name'], p['email']) for p in parsed_event['participants']]
    start_time = datetime.fromtimestamp(parsed_event['start_time']).strftime('%Y-%m-%d %H:%M:%S')
    location = parsed_event['location']
    description = parsed_event['description']

    # Format the output
    output = f"Title: {title}\n" \
                f"Participants:\n" + "\n".join([f"  Name: {name}, Email: {email}" for name, email in participants]) + "\n" \
                f"Start Time (UTC): {start_time}\n" \
                f"Location: {location}\n" \
                f"Description: {description}"
    return output


def format_event_for_nylas(parsed_event: Dict, emails_dict: Dict[str, str], start_time: int, end_time: int) -> Dict:
    """The start and end times must be an email dict."""
    participants = [{"name": name, "email": email} for name, email in emails_dict.items()]
    event_data = {
        "title": parsed_event['title'],
        "status": "confirmed",
        "busy": True,
        "participants": participants,
        "description": parsed_event['description'],
        "when": {
            "object": "timespan",
            "start_time": start_time,
            "end_time": end_time
        },
        "location": parsed_event['location']
    }
    return event_data


def generate_ics_calender(events, filename=None):
    """Save ics canender to a filename. None will save to a string instead.
    These events are deduced from messages with get_calendar_event."""
    calendar = ics.Calendar() # Make an empty calendar.

    for event_data in events:
        event = ics.Event()
        event.name = event_data['title']
        event.begin = datetime.fromtimestamp(event_data['start_time'])
        event.end = datetime.fromtimestamp(event_data['end_time'])
        event.description = event_data['description']
        event.location = event_data['location']

        for participant in event_data['participants']:
            event.add_attendee(f"{participant['name']} <{participant['email']}>")
        calendar.events.add(event)

    file_obj = open(filename, 'w', encoding='utf-8') if filename else io.StringIO()
    file_obj.writelines(calendar)
    out = file_obj.getvalue()
    file_obj.close()
    if filename:
        print(f"ICS file generated: {filename}")
    return out


#######################AI and Nylas APIs#############################

# NylasAPI class handles interactions with the Nylas API, such as retrieving calendars and creating events
class NylasAPI:
    def __init__(self, api_key: str, grant_id: str):
        self.api_key = api_key
        self.grant_id = grant_id

    def _get_headers(self) -> Dict[str, str]:
        # Returns the necessary headers for authentication with the Nylas API
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

    def get_calendars(self) -> List[Dict]:
        # Fetches all calendars associated with the grant ID
        url = f'https://api.us.nylas.com/v3/grants/{self.grant_id}/calendars'
        response = requests.get(url, headers=self._get_headers())
        return response.json()

    def get_events(self, calendar_id: str, limit=5) -> List[Dict]:
        # Fetches the latest events from a specific calendar
        url = f'https://api.us.nylas.com/v3/grants/{self.grant_id}/events?calendar_id={calendar_id}&limit={limit}'
        response = requests.get(url, headers=self._get_headers())
        return response.json()

    def create_event(self, calendar_id: str, event_data: Dict) -> Dict:
        # Creates a new event in the specified calendar
        url = f'https://api.us.nylas.com/v3/grants/{self.grant_id}/events?calendar_id={calendar_id}'
        response = requests.post(url, headers=self._get_headers(), data=json.dumps(event_data))
        return response.json()


# CalendarEvent model for storing event details, used in parsing responses from OpenAI
class CalendarEvent(BaseModel):
    title: str
    description: str
    when: str
    location: str
    participants: list[str]


# OpenAIClient class handles interactions with the OpenAI API, such as extracting event details and participants
class OpenAIClient:
    def __init__(self, timezone: str):
        self.client = AsyncOpenAI()
        self.timezone = timezone

    async def parse_event_description(self, description: str) -> Dict:
        """Uses GPT to convert the description into a CalendarEvent-as-dict format.
        description is a string such as John: bar,\n Joe: baz"""
        user_tz = pytz.timezone(self.timezone)
        current_time = datetime.now(user_tz).strftime("%Y-%m-%d %H:%M:%S")
        # Parses the event description to extract structured event details using OpenAI
        system_message = f"Extract the event details based on the following structure: title, description, when, location, and participants. The current date and time is {current_time}. Please ensure WHEN is a date or time description that can be converted into a standard date format. Put some details in the title. Missing parts fill with 'unknown'."
        completion = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": description},
            ],
            response_format=CalendarEvent
        )
        return json.loads(completion.choices[0].message.content)

    async def extract_participants(self, description: str) -> str:
        # Extracts participants' names and emails from the event description using OpenAI
        prompt = f"""
            Extract the participants' names and emails from the following event description. Return the result as a json of dictionaries, where each dictionary contains a "name" as a key and an "email" as a value. If the email is not available, set the value of "email" to None.
            For example:
            - If the input is "Alice will attend the meeting", return {{\"participants\": [{{\"name\": \"Alice\", \"email\": null}}]}}.
            - If the input is "Alice (alice@example.com) and Bob will attend the meeting", return {{\"participants\": [{{\"name\": \"Alice\", \"email\": \"alice@example.com\"}}, {{\"name\": \"Bob\", \"email\": null}}]}}.
        """

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": description}
            ],
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content

    async def extract_event_end_time(self, description: str) -> str:
        user_tz = pytz.timezone(self.timezone)
        current_time = datetime.now(user_tz).strftime("%Y-%m-%d %H:%M:%S")
        # Extract the end time, or provide an end time based on the current time and duration
        prompt = f"""
            Extract the end time from the following event description. The current date and time is {current_time}. 
            If the end time is not explicitly mentioned, try to calculate it based on the current time and the duration mentioned in the description. 
            Return the result as a string in the JSON format {{"end_time": "YYYY-MM-DD HH:MM:SS"}}.
            If can't get the end time, return 'unknown'.
            For example:
            - If the input is "The current date is 2023-09-15. The meeting will start at 3 PM and end at 4 PM", return {{"end_time": "2023-09-15 16:00:00"}}.
            - If the input is "The meeting will last for 2 hours", and the current time is "2023-09-15 14:00:00", return {{"end_time": "2023-09-15 16:00:00"}}.
        """

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": description}
            ],
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content


def _ensure_ai_key():
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
        os.environ[api_key_name] = api_key_val
_ensure_ai_key()
