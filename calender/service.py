import asyncio, pprint, os, re
import random
import json
from loguru import logger

from moobius import Moobius, MoobiusStorage, MoobiusWand
from moobius.types import Button, ButtonClick, MessageBody, InputComponent, Dialog
from moobius import types

import gpt

#####################################################################################################################

class CalendarService(Moobius):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not os.path.exists('debug'):
            os.makedirs('debug') # Ensure exists.
        self.channel_stores = {}
        self.imp = None # A helper Character agent that explains what is going on. Created once per startup.

    async def _update_char_list(self, channel_id, who=None):
        """See all people in the group chat."""
        if not who:
            who = await self.fetch_member_ids(channel_id, False)
        if type(who) is str:
            who = [who]
        visable_chars = [self.imp.character_id]+(await self.fetch_member_ids(channel_id, False))
        await self.send_characters(characters=visable_chars, channel_id=channel_id, recipients=who)

    async def _update_buttons(self, channel_id, user_id):
        """Button updates."""

        api_component = InputComponent(label="API Key", type=types.TEXT, required=True, placeholder="Nylas API key")
        grant_component = InputComponent(label="Grant ID", type=types.TEXT, required=True, placeholder="Nylas id")
        id_component = InputComponent(label="Calendar ID", type=types.TEXT, required=True, placeholder="Nylas calendar id")
        history_component = InputComponent(label="Specify how many recent chat messages to include OR text snippit from the oldest message. Limit of 96.",  type=types.TEXT, required=True, placeholder="16")
        save_nylas_component = InputComponent(label="Save to your Nylas calendar?", type=types.DROPDOWN, required=False, choices=['yes', 'no'], placeholder="no")
        timezone_component = InputComponent(label="Input your group's timezone", type=types.TEXT, required=True, placeholder="America/Los_Angeles")

        api_button_dia = Dialog(title='Input your Nylas keys', components=[api_component, grant_component, id_component])
        history_dia = Dialog(title='GPT extraction of event in the chat', components=[history_component, save_nylas_component])
        timezone_dia = Dialog(title='Time zone', components=[timezone_component])
        buttons = [Button(button_id='nylas', button_text='Input Nylas info', dialog=api_button_dia),
                   Button(button_id='calendar_msg', button_text='AI extract event', dialog=history_dia),
                   Button(button_id='set_timezone', button_text='Set Channel Timezone', dialog=timezone_dia),
                   Button(button_id='test', button_text='test')]
        await self.send_buttons(buttons, channel_id, [user_id])

    ################################# Getting the buttons to agree with the npcs ####################

    async def on_channel_init(self, channel_id):
        if not self.imp:
            self.imp = await self.create_agent(name='helper')
        self.channel_stores[channel_id] = MoobiusStorage(self.client_id, channel_id, self.config['db_config'])

    async def on_start(self, *args, **kwargs):
        pass

    async def on_spell(self, spell):
        print("THE SPELL:", spell)

    async def on_refresh(self, action):
        await self._update_buttons(action.channel_id, action.sender)
        await self._update_char_list(action.channel_id, action.sender)

    async def on_join_channel(self, action):
        await self._update_char_list(action.channel_id)

    async def on_leave_channel(self, action):
        await self._update_char_list(action.channel_id)

    async def on_button_click(self, button_click: ButtonClick):
        the_id = button_click.button_id

        store = self.channel_stores[button_click.channel_id]
        timezone = store.timezones.get('timezone', 'America/Los_Angeles')

        async def _process_message_pairs(pairs, show_nylas_format=False):
            senders = [p[0] for p in pairs]
            txts = [p[1] for p in pairs]
            try:
                event = await gpt.get_calendar_event(senders, txts, timezone=timezone)
            except Exception as e:
                await self.send_message('Error getting the calender event:\n'+str(e), button_click.channel_id, self.imp, await self.fetch_member_ids(button_click.channel_id))
                raise e
            await self.send_message('Event description:\n'+gpt.format_event_for_humans(event), button_click.channel_id, self.imp, await self.fetch_member_ids(button_click.channel_id))

            if button_click.arguments:
                cal_save = button_click.arguments[1].value.lower() in ['yes', 'y', 'true', True] # Nylas save.
            else:
                cal_save = False
            event1, excluded = gpt.format_event_for_nylas(event)
            if cal_save:
                api = store.user_nylas_keys.get(button_click.sender)
                if api:
                    response_info = gpt.save_event_to_nylas(parsed_event=event, nylas_api_key=api[0], nylas_grant_id=api[1], nylas_calendar_id=api[2])
                    if response_info.get('error'):
                        msg_txt = f'Error saving to Nylas calendar {api[2]}:\n'+str(response_info['error'])
                    else:
                        msg_txt = 'Saved to Nylas calendar: '+api[2]+('\n\n Warning: No emails found for '+(', '.join(excluded))+'.\nThese members were not added to the Nylas calender.' if excluded else '')
                    await self.send_message(msg_txt, button_click.channel_id, self.imp, button_click.sender)
                else:
                    await self.send_message('No Nylas API keys given to save it to, can paste in this JSON instead:\n'+json.dumps(event1, indent=2), button_click.channel_id, self.imp, button_click.sender)
            if show_nylas_format:
                await self.send_message('Debug Nylas JSON:\n'+json.dumps(event1, indent=2)+(' \n\nExcluded these members from the Nylas due to no email:\n'+str(excluded) if excluded else ''), button_click.channel_id, self.imp, button_click.sender)

        if the_id == 'nylas':
            api = button_click.arguments[0].value.strip()
            grant = button_click.arguments[1].value.strip()
            cal = button_click.arguments[2].value.strip()
            store.user_nylas_keys[button_click.sender] = [api, grant, cal]
            await self.send_message('Nylas credentials saved!', button_click.channel_id, self.imp, [button_click.sender])
        elif the_id == 'calendar_msg':
            name_txt_pairs = store.recent_messages.get('messages', [])
            lookback = button_click.arguments[0].value.lower() # 3 means will include three messages.
            N = len(name_txt_pairs)
            if re.search('[a-zA-Z]', lookback): # Search the message history for this message.
                for i in range(N):
                    if lookback.lower() in name_txt_pairs[i][1].lower():
                        lookback = N-i
                        break
                else:
                    await self.send_message('The lookback given was message text to search for and was not found. Using a default value of 12 instead.', button_click.channel_id, self.imp, button_click.sender)
                    lookback = 12
            else:
                lookback = int(lookback) # Intepret as int.
            lookback = min(lookback, N)
            name_txt_pairs0 = name_txt_pairs[-lookback:]; senders = [p[0] for p in name_txt_pairs0]; txts = [p[1] for p in name_txt_pairs0]
            await _process_message_pairs(name_txt_pairs0)
        elif the_id == 'set_timezone':
            timezone = button_click.arguments[0].value
            store.timezones['timezone'] = timezone
            await self.send_message('Timezone set to:'+timezone, button_click.channel_id, self.imp, await self.fetch_member_ids(button_click.channel_id))
        elif the_id == 'test':
            test_pairs = []
            test_pairs.append(['John Smith', 'John Smith invites you and Sarah Johnson to join the group chat "TechInnovate-VCF"'])
            test_pairs.append(['John Smith', """Hello everyone, let me introduce @Michael Brown, who is the founder of TechInnovate. They currently have two products, Nexus and Prism. @Sarah Johnson is a good friend of VCF. Michael usually stays in the Bay Area, but he might be in New York recently. Let's find a flexible time to connect!"""])
            test_pairs.append(['Sarah Johnson', "Thanks for the introduction, bro"])
            test_pairs.append(['Sarah Johnson', '@Michael Brown, nice to meet you Michael🤝'])
            test_pairs.append(['Michael Brown', """Hello, nice to meet you too. I'm currently based in the Bay Area!"""])
            test_pairs.append(['Sarah Johnson', """Great, are you available next week in the morning, your local time?"""])
            test_pairs.append(['Michael Brown', """Yes, I am. What day and time do you prefer? Could you give me your email? I'll have my "assistant" create a schedule😸"""])
            test_pairs.append(['Sarah Johnson', "How about Tuesday at 9:30 AM?"])
            test_pairs.append(['Sarah Johnson', "Haha ok"])
            test_pairs.append(['Baker Smith', "I would also like to join!"])
            test_pairs.append(['Sarah Johnson', "sjohnson@vcfinvest.com"])
            await self.send_message("Testing with this data:\n"+'\n'.join([str(p) for p in test_pairs]), button_click.channel_id, button_click.sender, [button_click.sender])
            await _process_message_pairs(test_pairs, True)
        else:
            await self.send_message('Unrecognized button: '+the_id, button_click.channel_id, self.imp, [button_click.sender])

    async def on_message_up(self, message_up: MessageBody):
        """Add to the history if it is a text message."""
        if message_up.subtype == types.TEXT:
            message_history = self.channel_stores[message_up.channel_id].recent_messages.get('messages')
            if not message_history:
                message_history = []
            sender_name =  (await self.fetch_character_profile(message_up.sender)).name
            message_history.append([sender_name, message_up.content.text]) # Name text pairs.
            while len(message_history) > 96: # Limit the length.
                message_history = message_history[1:]
            self.channel_stores[message_up.channel_id].recent_messages['messages'] = message_history
        all_but_the_sender = [r for r in message_up.recipients if r != message_up.sender]
        await self.send_message(message_up, recipients=all_but_the_sender)


if __name__ == "__main__":
    MoobiusWand().run(CalendarService, config='config/config.json')