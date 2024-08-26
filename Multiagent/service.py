import asyncio, pprint
from PIL import Image, ImageDraw
import hashlib, random
import json
from loguru import logger

from moobius import Moobius, MoobiusStorage
from moobius.types import Button, ButtonClick, MessageBody, InputComponent, Dialog
from moobius import types

import gpt

################################################## Prompt engineering part ##################################################
locations = {'dungeon':'You are bravely adventuring in a dungeon with monsters and treasure.',
             'tavern':'You are in the tavern to get a drink.',
             'academy':'You entered a classroom to learn about magic.',
             'plaza':'You are outside in a town, walking to your next locale.'}

all_the_names = ['Alice', 'Chen', 'Charlie', 'Omari', 'Andrea', 'Badr', 'Kunal', 'DoryFish']
all_the_personalities = {'Alice':'You love adventures, finding exploration in even the simplest of journeys.',
                         'Badr':'You are easily suprised, in both bad and good ways.',
                         'Kunal':'You are easily bored and rarely scared.',
                         'Charlie':'You often like to teach people about the history and creatures of this place, or about what they are talking about.',
                         'Omari':'You are quiet and tend to respond with single words and short phrases.'}
for name in all_the_names:
    if name not in all_the_personalities:
        all_the_personalities[name] = ''


def get_prepend(use_reAct, location, speakers_here, speaker, has_memory):
    """This is the system part of the prompt that goes before the memory itself."""

    # Prompt engineering fun:
    #prepend = [{'role':'assistant', 'content':'You are participating in a conversation, what follows is a list of who spoke what. Please respond to it.'}] # Does NOT work well at all.
    #prepend = [{'role':'user', 'content':'you are simulating a conversation at a public Plaza in the afternoon.'}] # It makes them simulate a multi-party conversation.
    #prepend = [{'role':'user', 'content':f'Please act as if you are a single person responding to the following conversation. Your name is {speaker}.'}] # Works ok.

    alone = len(speakers_here) == 1

    # https://app.wordware.ai/r/73fd941f-7127-47d3-a6a2-05d283274ea6
    if use_reAct:
        other_places = set(list(locations.keys()))
        other_places.remove(location)
        place_str = ', '.join(other_places)
        if has_memory:
            mem = '''
## Memories

Your memories are in other messages. Use these memories to inform your response.

'''
            new = ''''''
        else:
            mem = ''''''
            new = '''
You are just starting the conversation.
'''

        prompt = f'''
# Instructions

Your name is {speaker}. {locations[location]} You are also in a conversation with others.

Behave as a single person would behave.

{new}

## Personality

Your personality is as follows: {all_the_personalities[speaker]}

{mem}

## Response Format

Use the following format in your response:

Observation: What you see about the place you are in.
Thought: What do you think about this place and/or this conversation.
Speech: The spoken words you speak. Do not put any other words here.
Action: If you decide to move to another location (one of: {place_str}), state it here. Otherwise say that you stay put.

'''
        prepend = [{'role':'system', 'content':prompt}]
    else:
        first_message = locations[location]
        if alone:
            if not has_memory:
                first_message = first_message + f' Please speak your thoughts about this place you are in.'
            else:
                first_message = first_message + f' Your name is {speaker}.'
        else:
            if not has_memory:
                first_message = first_message + f' You are with other people. Please tell them about something that this place reminds you of. Your name is {speaker}.'
            else:
                first_message = first_message + f' Your name is {speaker}. You are with other people and are responding to the following conversation.'
        first_message = first_message + all_the_personalities[speaker]
        prepend = [{'role':'system', 'content':first_message}]
    return prepend


##########################################Memories and lossy compression#######################################################


async def summarize_fresh_spoken_memory(speaker, where_speaker_is, txt):
    """Summarizes a spoken memory."""
    where_speaker_is = _assert_loc(where_speaker_is)

    #prompt = [{'role':'system', 'content':'Please summarize this message: '+txt}]
    #with open('debug/last_speechsummary.txt', 'w') as f:
    #    json.dump(prompt, f, indent=3)
    #short_txt = await gpt.gpt_get_answer(prompt)

    return speaker + ' said "'+ txt + '" in the '+where_speaker_is


async def summarize_fresh_observation_memory(speaker, where_speaker_is, txt):
    """The observation part."""
    where_speaker_is = _assert_loc(where_speaker_is)

    #prompt = [{'role':'system', 'content':'Please summarize this message: '+txt}]
    #with open('debug/last_seesummary.txt', 'w') as f:
    #    json.dump(prompt, f, indent=3)
    #short_txt = await gpt.gpt_get_answer(prompt)

    return speaker + ' saw '+ txt + ', in the '+where_speaker_is


async def summarize_fresh_thought_memory(speaker, where_speaker_is, txt):
    """The thought part."""
    where_speaker_is = _assert_loc(where_speaker_is)

    #prompt = [{'role':'system', 'content':'Please summarize this message: '+txt}]
    #with open('debug/last_thinksummary.txt', 'w') as f:
    #    json.dump(prompt, f, indent=3)
    #short_txt = await gpt.gpt_get_answer(prompt)

    return speaker + ' thought about '+ txt + ', in the '+where_speaker_is


async def summarize_fresh_move_memory(speaker, where_speaker_is, next_loc):
    """A summary of a memory of traveling. Can use open ai if desired, but it so simple it is not needed."""
    next_loc = _assert_loc(next_loc)
    return speaker + ' travelled from the '+ where_speaker_is + ' to the '+ next_loc


async def append_simplify_memories(name, the_memory, new_memories, location):
    """Appends this memory to list-valued "the_memory".
    Will also condense old memories if the need arises."""
    if name == 'DoryFish': # Finding Nemo.
        return []

    the_memory.extend(new_memories)

    async def _len_limit(mem, numword):
        if numword==0:
            return ''
        mem = mem.strip()
        if len(mem.split(' '))<=numword:
            return mem
        prompt = '''
# Instructions

You are to summarize the next message after this one. The summary must be at most {numword} words.

# Response format

You must return your response as a list of words and/or sentences. The maximum number of words total is {numword}.
'''
        out = await gpt.gpt_get_answer([{'role':'system', 'content':prompt}, {'role':'user', 'content':mem}])
        pieces = out.strip().split(' ')
        if len(pieces)<=numword:
            return out
        if numword==1:
            return pieces[0]
        out = ' '.join(pieces[0:numword-1]+[pieces[-1]])+'...'
        return out

    # Shorten single memories:
    shrinkize = [256, 128, 64, 32, 16, 8, 7, 6]
    shrinkize = shrinkize+[shrinkize[-1]]*len(the_memory)
    for i in range(len(the_memory)):
        age = len(the_memory)-i-1 # Zero for the most recent memory.
        numword = shrinkize[age]
        the_memory[i] = await _len_limit(the_memory[i], numword)

    # Shorten the total array:
    max_memory = 64 # TODO: Include a summarizer instead of just forgetting about old stuff.
    num_compress = 8
    if len(the_memory) > max_memory:
        compressed_mem = _len_limit('\n'.join(the_memory[0:num_compress]))
        the_memory = [compressed_mem]+the_memory[num_compress+1:]

    return the_memory


#####################################################################################################################


def _assert_loc(loc):
    loc = loc.lower().strip()
    if loc == 'all':
        return 'all'
    if loc not in locations:
        raise Exception(f'Invalid location: {loc}')
    return loc


def make_image(name, avatar):
    """Nice? looking image."""

    seed = int.from_bytes(hashlib.sha256(name.encode()).digest(), byteorder='big')
    random.seed(seed)

    res = 384

    img = Image.new('RGB', (res, res), color='white')
    draw = ImageDraw.Draw(img)

    hair_num = int((40.0*random.random())**1.5)
    hair_radius = 0.25*random.random()+0.15
    hair_xs = [res*(0.5-hair_radius + i*2*hair_radius/(hair_num-0.999)) for i in range(hair_num)]
    hair_col = (int(40*random.random()), int(40*random.random()), int(40*random.random()))
    hair_wind = 0.08*(random.random()-0.5)
    for hair_x in hair_xs:
        start_point = (int(hair_x+res*hair_wind), int(res*0.125*random.random()+res*0.02))
        end_point = (int(hair_x+0.02*random.random()), res*0.5)
        draw.line([start_point, end_point], fill=hair_col, width=2)

    center = (int(res*0.5), int(res*0.5))
    radius = 100+25*random.random()
    stretch = 0.875+0.25*random.random()
    draw.ellipse([center[0] - int(radius*stretch), center[1] - int(radius), 
                center[0] + int(radius*stretch), center[1] + int(radius)],
                fill=(int(160*random.random()), int(160*random.random()), int(160*random.random())),
                outline=(int(40*random.random()), int(40*random.random()), int(40*random.random())), width=3+int(2*random.random()))

    delta = [(random.random()-0.5)*0.0625, (random.random()-0.5)*0.0625]
    for o in [-1, 1]:
        center = (int(res*0.5+res*0.125*o+res*delta[0]*o), int(res*0.4+res*delta[1]))
        radius = 0.0625*res
        draw.ellipse([center[0] - int(radius), center[1] - int(radius), 
                    center[0] + int(radius), center[1] + int(radius)],
                    fill=(int(20*random.random()), int(20*random.random()), int(20*random.random())), width=2)
        draw.ellipse([center[0] - int(radius*0.75), center[1] - int(radius*0.75), 
                    center[0] + int(radius*0.75), center[1] + int(radius*0.75)],
                    fill=(int(20*random.random()+180), int(20*random.random()+180), int(20*random.random()+180)), width=2)

    delta = (random.random()-0.5)*0.0625
    center = (int(res*0.5), int(res*0.65+res*delta))
    radius = 0.08*res
    stretch = 1.5
    draw.ellipse([center[0] - int(radius*stretch), center[1] - int(radius + delta*res),
                center[0] + int(radius*stretch), center[1] + int(radius - delta*res)],
                fill=(int(20*random.random()), int(20*random.random()), int(20*random.random())), width=2)

    img.save(avatar)
make_image('test', 'test.png')


def _maybe_moving_to(cur_loc, action_txt):
    """Does it move to a new location? None if not moving."""
    action_txt = action_txt.lower().strip()
    nw = len(action_txt.split(' '))

    if 'stay put' in action_txt:
        return False
    if 'stay' in action_txt and nw < 6:
        return False
    for l in locations.keys():
        if l in action_txt and l != cur_loc:
            return l
    logger.error('Cannot figure out if this is a move-to action: '+ action_txt)


class NPCService(Moobius):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.imp = {}
        self.npcs = {} # Dict from name to Character.
        self.convo_active = {} # Is there an conversation on a given channel.
        self.loop_started = False

    async def on_channel_init(self, channel_id):
        self.channels[channel_id] = MoobiusStorage(self.client_id, channel_id, self.config['db_config'])
        # .memory = Dict from name to memory, which is a list of strings.
        # .world['speaker_history'] is the history of who spoke when.
        # .world['where'] is where each person is.
           #  Maybe other keys such as 'events' will be added in teh future.

        async def upload1(name):
            avatar = f'./logs/tmp{name}.png'
            make_image(name, avatar)
            return await self.create_agent(name=name, avatar=avatar, description="AI!")

        if not self.npcs:
            self.imp = await self.create_agent(name='imp')
            for name in all_the_names:
                self.npcs[name] = upload1(name=name)
        self.npcs = dict(zip(self.npcs.keys(), await asyncio.gather(*self.npcs.values())))

    def get_memory(self, channel_id, name):
        """Returns the memory."""
        memory = self.channels[channel_id].memory
        return memory.get(name, [])

    async def step_conversation(self, channel_id, speaker_id=None, txt=None):
        """
        Takes a step in the conversation, updating the history and saving the message.
        Also people can move around.
        Both human or AI messages apply!
        Use None speaker_id for an AI step or specify a message.
        """
        names = sorted(list(self.npcs.keys()))
        where_chars_are = await self.get_char_locations(channel_id)

        world = self.channels[channel_id].world
        world['speaker_history'] = world.get('speaker_history', ['the_wind', 'howl', 'plaza'])
        world['where'] = world.get('where', dict(zip(names, ['plaza']*len(names))))

        #for wk in world.keys(): # TMP DEBUG does not seem to be a problem.
        #    if wk not in world:
        #        raise Exception('Cached Dict key "in" failure.')

        ai_word_find = True # Indicate they are looking for words.
        char_ids = await self.fetch_member_ids(channel_id)

        if speaker_id:
            speaker = (await self.fetch_character_profile(speaker_id)).name
        else:
            # Round-robin speakers:
            last_speaker = world['speaker_history'][-1][0]
            if last_speaker in names:
                speaker = (names+[names[0]])[names.index(last_speaker)+1]
            else:
                speaker = names[0]

        where_speaker_is = where_chars_are[speaker]
        speakers_here = []
        for name in names:
            if where_chars_are[name] == where_speaker_is or where_speaker_is=='all':
                speakers_here.append(name)

        move_report_task = None
        is_ai = not txt
        is_reAct = self.channels[channel_id].reAct_mode.get('enabled', False)
        observation_mem = None
        thought_mem = None
        spoken_mem = None
        next_loc = None
        if is_ai: # Use AI to determine the txt.

            speaker_memory = self.get_memory(channel_id, speaker)

            prepend = get_prepend(is_reAct, where_speaker_is, speakers_here, speaker, len(speaker_memory) > 0)

            # Load the memory:
            #the_messages = prepend+[{'role':'user', 'user_id':who, 'content':txt} for who, txt, where in speaker_memory]
            the_messages = prepend+[{'role':'user', 'content':mem} for mem in speaker_memory]

            speaker_id = self.npcs[speaker].character_id
            if ai_word_find:
                await self.send_message('<thinking>', channel_id=channel_id, sender=speaker_id, recipients=char_ids)
            gpt_txt = await gpt.gpt_get_answer(the_messages)
            with open('debug_last_prompt.txt', 'w') as f:
                json.dump(the_messages, f, indent=3)
            if is_reAct:
                tmp_sgn = '--<>--'
                txt = gpt_txt
                for kw in ['Observation', 'Thought', 'Action', 'Speech']:
                    txt = txt.replace(kw+':',f'\n## {kw}\n')
                    gpt_txt = gpt_txt.replace(kw+':', tmp_sgn+kw+':')
                txt = txt.strip()
                pieces = gpt_txt.split(tmp_sgn)
                for p in pieces:
                    p = p.strip()
                    if p.startswith('Observation:'):
                        observation_mem = p.replace('Observation:','')
                    if p.startswith('Thought:'):
                        thought_mem = p.replace('Thought:','')
                    if p.startswith('Speech:'):
                        spoken_mem = p.replace('Speech:','')
                    if p.startswith('Action:'):
                        p = p.replace('Action:','')
                        next_loc = _maybe_moving_to(where_speaker_is, p)
            else:
                txt = gpt_txt
                spoken_mem = txt
                crowd_score = len(speakers_here)/(len(where_chars_are)+0.00001) # Higher chance of leaving crowded areas.
                move_chance = 0.05 + 0.45*crowd_score

                if random.random()<=move_chance: # Move after speaking.
                    next_loc = random.choice(list(locations.keys()))
                    if next_loc != where_speaker_is:
                        move_report_task = lambda: self.send_message(f'<about to travel from {where_speaker_is} to {next_loc}>', channel_id=channel_id, sender=speaker_id, recipients=char_ids)
                    world['where'][speaker] = next_loc
                    await self._update_char_list(channel_id, all=True) # Show locations of characters.
        else:
            spoken_mem = txt

        move_mem = None
        if next_loc:
            move_mem = await summarize_fresh_move_memory(speaker, where_speaker_is, next_loc)
        if spoken_mem:
            world['speaker_history'].append([speaker, spoken_mem, where_speaker_is])
            world['speaker_history'] = world['speaker_history'] # Save to disk.

            spoken_mem = await summarize_fresh_spoken_memory(speaker, where_speaker_is, spoken_mem)
        if observation_mem:
            observation_mem = await summarize_fresh_observation_memory(speaker, where_speaker_is, observation_mem)
        if thought_mem:
            thought_mem = await summarize_fresh_thought_memory(speaker, where_speaker_is, thought_mem)

        # Store the memory:
        memory = self.channels[channel_id].memory
        new_mems = {} # Name to list of new memories.
        for i, new_memory in enumerate([move_mem, observation_mem, thought_mem, spoken_mem]):
            if new_memory:
                new_mems[speaker] = new_mems.get(speaker, []) + [new_memory.replace(speaker, 'I')]
                if i in [0, 3]:
                    for name in speakers_here:
                        if name != speaker:
                            new_mems[name] = new_mems.get(name, []) + [new_memory]

        mems_tasks = {}
        for name, v in new_mems.items():
            mems_tasks[name] = append_simplify_memories(name, memory.get(name, []), v, where_chars_are[name])

        await self.send_message(f'({where_speaker_is})\n'+txt, channel_id=channel_id, sender=speaker_id, recipients=char_ids)
        if len(mems_tasks) > 0:
            await self.send_message(f'<{list(mems_tasks.keys())} are consolidating thier memories>', channel_id=channel_id, sender=self.imp.character_id, recipients=char_ids)
        mems_consolidated = dict(zip(mems_tasks.keys(), await asyncio.gather(*mems_tasks.values())))

        for name,v in mems_consolidated.items():
            memory[name] = v
        if len(mems_tasks) > 0:
            await self.send_message(f'Done!', channel_id=channel_id, sender=self.imp.character_id, recipients=char_ids)

        if move_report_task:
            await move_report_task()

    async def on_spell(self, spell):
        print("THE SPELL:", spell)

    async def get_char_locations(self, channel_id):
        """Locations of each character, both real and virual, by name, not the id. Default to random. Adds and removes from world['where']"""
        where = self.channels[channel_id].world.get('where',{})
        names = list(self.npcs.keys())
        fetch_tasks = []
        for real_id in (await self.fetch_member_ids(channel_id)):
            fetch_tasks.append(self.fetch_character_profile(real_id))
        names = names + [c.name for c in (await asyncio.gather(*fetch_tasks))] # Could cache this to reduce fetching.

        for name in names:
            where[name] = where.get(name, random.choice(list(locations.keys())))
        self.channels[channel_id].world['where'] = where # Save to disk.
        return where

    async def _update_char_list(self, action_or_channel_id, all=False):
        if hasattr(action_or_channel_id, 'channel_id'):
            channel_id = action_or_channel_id.channel_id
        else:
            channel_id = action_or_channel_id
        all_ids = await self.fetch_member_ids(channel_id, False)+[c.character_id for c in list(self.npcs.values())]
        locs = await self.get_char_locations(channel_id)
        rename_tasks = []
        for name, char in self.npcs.items():
            rename_tasks.append(self.update_agent(char.character_id, char.avatar, 'Agent', name + f' [{locs[name]}]'))
        await asyncio.gather(*rename_tasks)
        if all:
            ids = all_ids
        else:
            ids = [action_or_channel_id.sender] # Must be an action in this case.
        await self.send_characters(characters=all_ids, channel_id=channel_id, recipients=ids)

    async def on_refresh(self, action):
        await self._update_buttons(action.channel_id, action.sender)
        await self._update_char_list(action, all=False)

    async def ai_loop(self):
        while True:
            for channel_id, is_active in self.convo_active.items():
                if is_active: # Schedule another AI response.
                    await self.step_conversation(channel_id, speaker_id=None, txt=None)
            await asyncio.sleep(0.25)

    async def on_join_channel(self, action):
        await self._update_char_list(action, all=True)

    async def on_leave_channel(self, action):
        await self._update_char_list(action, all=True)

    async def _update_buttons(self, channel_id, user_id):
        """Button updates."""
        name = (await self.fetch_character_profile(user_id)).name
        places = sorted(list(locations.keys())+['all'])
        where = self.channels[channel_id].world.get('where',{})
        rea = self.channels[channel_id].reAct_mode.get('enabled', False)
        going = self.convo_active.get(channel_id, False)

        component = InputComponent(label="Places", type=types.DROPDOWN, required=True, choices=places, placeholder="plaza")
        travel_button_args = [Dialog(title='Choose destination!', components=[component])]
        buttons = [Button(button_id='startpause', button_text='Pause ' if going else 'Start '+'AI convo!'),
                   Button(button_id='step', button_text='Take one AI step'),
                   Button(button_id='list_memories', button_text='Show current memories'),
                   Button(button_id='clear_memories', button_text='Delete memories'),
                   Button(button_id='toggle_ReAct', button_text='Disable ReAct' if rea else 'Enable ReAct'),
                   Button(button_id='travel', button_text=f'Travel (at {where.get(name, "plaza")})', dialog=travel_button_args)]
        await self.send_buttons(buttons, channel_id, [user_id])

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
                if not self.loop_started:
                    self.loop_started = True
                    asyncio.create_task(self.ai_loop())
        elif button_click.button_id == 'toggle_ReAct':
            rea = self.channels[button_click.channel_id].reAct_mode.get('enabled', False)
            rea = not rea
            self.channels[button_click.channel_id].reAct_mode['enabled'] = rea
            await self.send_message(f'ReAct mode (https://arxiv.org/pdf/2210.03629) set to {rea}', button_click.channel_id, button_click.sender, [button_click.sender])
        elif button_click.button_id == 'step':
            await self.step_conversation(button_click.channel_id, speaker_id=None, txt=None)
        elif button_click.button_id == 'list_memories':
            for name, char in self.npcs.items():
                memory_of_name = self.get_memory(button_click.channel_id, name)
                msgs = ['What I remember:']+['>'+m+'\n' for m in memory_of_name]
                if len(memory_of_name) == 0:
                    msgs = ['I have no memories yet.']
                msg = '\n'.join(msgs)
                await self.send_message(msg, button_click.channel_id, char.character_id, [button_click.sender])
        elif button_click.button_id == 'clear_memories':
            await self.send_message('You cast Obliviate on everyone and they forget everything', button_click.channel_id, button_click.sender, [button_click.sender])
            for name, char in self.npcs.items():
                self.channels[button_click.channel_id].memory[name] = []
        elif button_click.button_id == 'travel':
            if not button_click.arguments:
                return # Nothing specified.
            to_here = button_click.arguments[0].value
            name = (await self.fetch_character_profile(button_click.sender)).name
            self.channels[button_click.channel_id].world['where'][name] = to_here
            await self.send_message('You traveled to the '+to_here, button_click.channel_id, button_click.sender, [button_click.sender])
        await self._update_buttons(button_click.channel_id, button_click.sender)

    async def on_message_up(self, message_up: MessageBody):
        """Add to the history if it is a text message."""
        if message_up.subtype == types.TEXT:
            await self.step_conversation(message_up.channel_id, speaker_id=message_up.sender, txt=message_up.content.text)
        else:
            await self.send_message(message_up)
