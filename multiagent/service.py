import asyncio, pprint, os
import random
import json
from loguru import logger

from moobius import Moobius, MoobiusStorage, MoobiusWand
from moobius.types import Button, ButtonClick, MessageBody, InputComponent, Dialog
from moobius import types

import worldbuilder, gpt, avatar_maker

#####################################################################################################################

async def chunked_gather(tasks, n=4):
    """Limit how many at once. Fights against "service unavilable" errors."""
    out = []
    while tasks:
        n0 = min(n, len(tasks))
        out.extend(await asyncio.gather(*tasks[0:n0]))
        tasks = tasks[n0:]
    return out


class NPCService(Moobius):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not os.path.exists('debug'):
            os.makedirs('debug') # Ensure exists.
        self.channel_stores = {} # Channel storages persistent to disk: world, reAct_mode, real_user_locations (id-keyed)
        self.npcs = {} # Dict from name to Character object, created once per startup or world update.
        self.imp = None # A helper Character agent that explains what is going on. Created once per startup.
        self.convo_active = {} # Is a conversation "world" active on each channel? It is reset to False every startup.

    ################################# Updating each person's view to agree with that the world is ####################

    async def _update_char_list(self, channel_id, who=None):
        """Updates what each person sees in the channel. Can also specify only a specific person."""

        ## Step one: Update the NPCS.
        world = self.get_world(channel_id)

        async def upload1(name):
            avatar = f'./logs/tmp{name}.png'
            avatar_maker.make_image(name, avatar)
            out = await self.create_agent(name=name, avatar=avatar, description="AI!")
            self.npcs[name] = out
            return out
        new_char_tasks = []
        for name in world.people.keys():
            if name not in self.npcs:
                new_char_tasks.append(upload1(name=name))
        await chunked_gather(new_char_tasks)

        rename_tasks = []
        for name in world.people.keys():
            loc = world.people_where.get(name, 'unknown')
            char = self.npcs[name]
            rename_tasks.append(self.update_agent(char.character_id, char.avatar, 'Agent', name + f' [{loc}]'))
        await chunked_gather(rename_tasks)

        ## Step two: Update what the users can see. Note: Users can see characters not in thier location.
        if not who:
            who = await self.fetch_member_ids(channel_id, False)
        if type(who) is str:
            who = [who]
        visable_chars = [self.imp.character_id]+(await self.fetch_member_ids(channel_id, False))+[self.npcs[name].character_id for name in sorted(list(world.people.keys()))]

        await self.send_characters(characters=visable_chars, channel_id=channel_id, recipients=who)

    async def _update_buttons(self, channel_id, user_id):
        """Button updates."""
        world = self.get_world(channel_id)

        name = (await self.fetch_character_profile(user_id)).name
        places = sorted(list(world.locations.keys()))+['all']
        rea = self.channel_stores[channel_id].reAct_mode.get('enabled', False)
        going = self.convo_active.get(channel_id, False)

        player_is_here = self.channel_stores[channel_id].real_user_locations.get(user_id, "all")
        travel_component = InputComponent(label="Places", type=types.DROPDOWN, required=True, choices=places, placeholder="plaza")
        travel_button_dia = Dialog(title='Choose destination!', components=[travel_component])
        buttons = [Button(button_id='startpause', button_text='Pause ' if going else 'Start '+'AI convo!'),
                   Button(button_id='step', button_text='One AI step'),
                   Button(button_id='list_memories', button_text='Show memories'),
                   Button(button_id='clear_memories', button_text='Delete memories'),
                   Button(button_id='change_world', button_text='Edit World'),
                   Button(button_id='toggle_ReAct', button_text='Disable ReAct' if rea else 'Enable ReAct'),
                   Button(button_id='travel', button_text=f'Travel (at {player_is_here})', dialog=travel_button_dia)]
        await self.send_buttons(buttons, channel_id, [user_id])

    ################################# Getting the buttons to agree with the npcs ####################

    def get_world(self, channel_id):
        """Sets a default world if there is no such world."""
        if self.channel_stores[channel_id].world_dict:
            return worldbuilder.from_dict(self.channel_stores[channel_id].world_dict)
        return worldbuilder.MMOWorld() # Default.

    async def update_to_world(self, channel_id, world):
        """Sets the world of a channel id, updating locations etc. Can be used to reset everything, etc."""
        world.compat()
        for ky, v in world.to_dict().items(): # Key by key, so that it saves the CachedDict object properly.
            self.channel_stores[channel_id].world_dict[ky] = v
        who_to_update_to = await self.fetch_member_ids(channel_id, False)
        await chunked_gather([self._update_buttons(channel_id, who) for who in who_to_update_to])
        await self._update_char_list(channel_id, who_to_update_to)

    async def on_channel_init(self, channel_id):
        if not self.imp:
            self.imp = await self.create_agent(name='Imp')
        self.channel_stores[channel_id] = MoobiusStorage(self.client_id, channel_id, self.config['db_config'])
        self.convo_active[channel_id] = False
        await self.update_to_world(channel_id, self.get_world(channel_id))

    def get_memory(self, channel_id, npc_name):
        """Returns the memory of a given AI. Older memories generally get more and more abbreviated."""
        world = self.get_world(channel_id)
        if npc_name not in world.people:
            return ['This person does not exist in the world.']
        return world.people_memories.get(npc_name, [])

    async def step_conversation(self, channel_id, speaker_id=None, txt=None):
        """
        Takes a step in the conversation, updating the history and saving the message.
        Also people can move around.
        Both human or AI messages apply!
        Use None speaker_id for an AI step or specify a message.
        """
        is_reAct = self.channel_stores[channel_id].reAct_mode.get('enabled', False)
        if speaker_id:
            speaker_name = (await self.fetch_character_profile(speaker_id)).name
        else:
            speaker_name = None # Let the AI detect it.
        if speaker_id:
            location = self.channel_stores[channel_id].real_user_locations.get(speaker_id, 'all')
        else:
            location = None

        world = self.get_world(channel_id)

        real_ids = await self.fetch_member_ids(channel_id)
        def _send_message_f(speaker_name, txt):
            if speaker_name:
                speaker_id = self.npcs[speaker_name].character_id
            else:
                speaker_id = self.imp.character_id
            loop = asyncio.get_event_loop()
            loop.create_task(self.send_message(txt, channel_id=channel_id, sender=speaker_id, recipients=real_ids))
        await world.step_world(speaker_name=speaker_name, location=location, txt=txt, is_reAct=is_reAct, send_message_f=_send_message_f)
        await self.update_to_world(channel_id, world)

    async def on_start(self, *args, **kwargs):
        asyncio.create_task(self.ai_loop())

    async def on_spell(self, spell):
        print("THE SPELL:", spell)

    async def on_refresh(self, action):
        await self._update_buttons(action.channel_id, action.sender)
        await self._update_char_list(action.channel_id, action.sender)

    async def ai_loop(self):
        while True:
            for channel_id, is_active in self.convo_active.items():
                if is_active: # Schedule another AI response.
                    await self.step_conversation(channel_id, speaker_id=None, txt=None)
            await asyncio.sleep(0.25)

    async def on_join_channel(self, action):
        await self._update_char_list(action.channel_id)

    async def on_leave_channel(self, action):
        await self._update_char_list(action.channel_id)

    async def on_button_click(self, button_click: ButtonClick):
        if button_click.button_id == 'hi':
            await self.send_message("I am thinking...", button_click.channel_id, self.npcs['Alice'].character_id, [button_click.sender])
            txt = await gpt.gpt_get_answer([{'role':'user', 'content':'I say hi to you!', 'user_id':button_click.sender}])
            await self.send_message(txt, button_click.channel_id, self.npcs['Alice'].character_id, [button_click.sender])
        elif button_click.button_id == 'startpause':
            self.convo_active[button_click.channel_id] = self.convo_active.get(button_click.channel_id, False)
            if self.convo_active[button_click.channel_id]:
                await self.send_message('You use your magic spell to stop the AIs from talking (note: they get one chance to finish thier sentence!)', button_click.channel_id, button_click.sender, [button_click.sender])
                self.convo_active[button_click.channel_id] = False
            else:
                await self.send_message('Your hear the AIs beginning to talk', button_click.channel_id, button_click.sender, [button_click.sender])
                self.convo_active[button_click.channel_id] = True
        elif button_click.button_id == 'toggle_ReAct':
            rea = self.channel_stores[button_click.channel_id].reAct_mode.get('enabled', False)
            rea = not rea
            self.channel_stores[button_click.channel_id].reAct_mode['enabled'] = rea
            await self.send_message(f'ReAct mode (https://arxiv.org/pdf/2210.03629) set to {rea}', button_click.channel_id, button_click.sender, [button_click.sender])
        elif button_click.button_id == 'change_world':
            msg = '''
Send the following commands **to the Imp (and only the Imp)** to change the world:

People ...: Type in a JSON dict from name to personality descrption. Or leave empty to print the current personalities.

Places ...: Type in a JSON dict from place name to place description. Or leave empty to print the current places.

Prompt-people ...: Tell the AI, in natural language, to generate a list of people with personalities via Structured Response.

Prompt-places ...: Tell the AI, in natural language, to generate a list of places with descriptions via Structured Response.

Reset: Reset to the default world and people.

'''.strip()
            await self.send_message(msg, button_click.channel_id, self.imp, [button_click.sender])
        elif button_click.button_id == 'step':
            await self.step_conversation(button_click.channel_id, speaker_id=None, txt=None)
        elif button_click.button_id == 'list_memories':
            world = self.get_world(button_click.channel_id)
            for name, char in self.npcs.items():
                if name not in world.people:
                    continue
                memory_of_name = self.get_memory(button_click.channel_id, name)
                #msgs = ['What I remember:']+['>'+m+'\n' for m in memory_of_name]
                msgs = ['What I remember:']+memory_of_name
                if len(memory_of_name) == 0:
                    msgs = ['What are memories?'] if name == 'DoryFish' else ['I have no memories yet.']
                msg = '\n.....\n'.join(msgs)
                await self.send_message(msg, button_click.channel_id, char, [button_click.sender])
        elif button_click.button_id == 'clear_memories':
            await self.send_message('You cast Obliviate on everyone and they forget everything', button_click.channel_id, button_click.sender, [button_click.sender])
            world = self.get_world(button_click.channel_id)
            world.people_memories = {}
            await self.update_to_world(button_click.channel_id, world)
        elif button_click.button_id == 'travel':
            if not button_click.arguments:
                return # Nothing specified.
            to_here = button_click.arguments[0].value
            #name = (await self.fetch_character_profile(button_click.sender)).name
            self.channel_stores[button_click.channel_id].real_user_locations[button_click.sender] = to_here
            if to_here == 'all':
                msg = 'You cast a clone spell and are everywhere at once. Everyone can hear you speak.'
            else:
                msg = 'You traveled to the '+to_here+'.\n\n'+self.get_world(button_click.channel_id).locations[to_here]
            await self.send_message(msg, button_click.channel_id, button_click.sender, [button_click.sender])
        await self._update_buttons(button_click.channel_id, button_click.sender)

    async def on_message_up(self, message_up: MessageBody):
        """Add to the history if it is a text message."""
        if message_up.subtype == types.TEXT:
            #print("GOT MESSAGE for:", message_up.recipients, 'IMP ID is:', self.imp.character_id)
            if len(message_up.recipients) == 1 and message_up.recipients[0] == self.imp.character_id: # Edit world messages.
                users = await self.fetch_member_ids(message_up.channel_id)
                txt = message_up.content.text.strip()
                prompts = {'people':'people', 'places':'places',
                           'prompt people':'prompt-people', 'prompt-people':'prompt-people', 'prompt_people':'prompt-people',
                           'prompt places':'prompt-places', 'prompt-places':'prompt-places', 'prompt_places':'prompt-places',
                           'reset':'reset'}
                for ky, v in list(prompts.items()):
                    prompts[ky+':'] = v
                the_prompt = None
                txt_body = None
                for p0, p1 in prompts.items():
                    if txt.lower().startswith(p0.lower()):
                        if not the_prompt or len(p0)>len(the_prompt):
                            txt_body = txt[len(p0):].strip()
                            the_prompt = p1
                attr = None
                if the_prompt == 'people':
                    attr = 'people'
                elif the_prompt == 'places':
                    attr = 'locations'
                if attr:
                    if len(txt_body) == 0: # Print it out.
                        out = json.dumps(getattr(self.get_world(message_up.channel_id), attr), indent=2)
                        await self.send_message(message_up, text=out, recipients=users)
                    else:
                        try:
                            x = json.loads(txt_body)
                        except Exception as e:
                            await self.send_message(message_up, text='JSON read error: '+str(e), recipients=users)
                            return
                        if type(x) is not dict:
                            await self.send_message(message_up, text='Data format error, not a dict', recipients=users)
                        if not x:
                            await self.send_message(message_up, text='Data format error, empty dict', recipients=users)
                        x = dict(zip([str(ky) for ky in x.keys()], [str(v) for v in x.values()]))
                        world = self.get_world(message_up.channel_id)
                        setattr(world, attr, x)
                        await self.update_to_world(message_up.channel_id, world)
                if the_prompt == 'prompt-people':
                    persons = await gpt.gpt_make_people(txt_body, temperature=0.5, model="gpt-4o-mini", num_default=8)
                    world = self.get_world(message_up.channel_id)
                    world.people = persons
                    world.people_memories = {}
                    await self.update_to_world(message_up.channel_id, world)
                    await self.send_message(message_up, text='The AI created these people:\n'+str(world.people), recipients=users)
                elif the_prompt == 'prompt-places':
                    places = await gpt.gpt_make_places(txt_body, temperature=0.5, model="gpt-4o-mini", num_default=6)
                    world = self.get_world(message_up.channel_id)
                    world.locations = places
                    #world.people_memories = {} # Let them keep old memories from the places.
                    await self.update_to_world(message_up.channel_id, world)
                    await self.send_message(message_up, text='The AI created these places:\n'+str(world.locations), recipients=users)
                elif the_prompt == 'reset':
                    await self.update_to_world(message_up.channel_id, worldbuilder.MMOWorld())
                elif not the_prompt:
                    await self.send_message(message_up, text='Did not recognize prompt for command:'+str(txt.split(' ')[0]), recipients=users)

                if the_prompt:
                    await self.send_message(message_up, text='Command finished: '+str(the_prompt), recipients=users)
            else:
                await self.step_conversation(message_up.channel_id, speaker_id=message_up.sender, txt=message_up.content.text)
        else:
            await self.send_message(message_up)


if __name__ == "__main__":
    MoobiusWand().run(NPCService, config='config/config.json')