# Tools for making, running, and managing a virtual world. This code should not include any interaction with the Moobius platform.
import random, json, asyncio

from loguru import logger
import gpt

######################## Non-AI support functions #################################

def _maybe_moving_to(cur_loc, action_txt, location_names):
    """Does it move to a new location? None if not moving."""
    action_txt = action_txt.lower().strip()
    nw = len(action_txt.split(' '))

    if 'stay put' in action_txt:
        return False
    if 'stay' in action_txt and nw < 6:
        return False
    for l in location_names:
        if l in action_txt and l != cur_loc:
            l = _assert_loc(l, location_names)
            return l
    logger.error('Cannot figure out if this is a move-to action: '+ action_txt)


def _assert_loc(loc, locations):
    loc = loc.lower().strip()
    if loc == 'all':
        return 'all'
    if loc not in locations:
        raise Exception(f'Invalid location: {loc}')
    return loc


def summarize_fresh_spoken_memory(speaker, where_speaker_is, txt):
    """Summarizes a spoken memory."""

    #prompt = [{'role':'system', 'content':'Please summarize this message: '+txt}]
    #with open('debug/last_speechsummary.txt', 'w') as f:
    #    json.dump(prompt, f, indent=3)
    #short_txt = await gpt.gpt_get_answer(prompt)

    return speaker + ' said "'+ txt + '" in the '+where_speaker_is


def summarize_fresh_observation_memory(speaker, where_speaker_is, txt):
    """The observation part."""

    #prompt = [{'role':'system', 'content':'Please summarize this message: '+txt}]
    #with open('debug/last_seesummary.txt', 'w') as f:
    #    json.dump(prompt, f, indent=3)
    #short_txt = await gpt.gpt_get_answer(prompt)

    return speaker + ' saw '+ txt + ', in the '+where_speaker_is


def summarize_fresh_thought_memory(speaker, where_speaker_is, txt):
    """The thought part."""

    #prompt = [{'role':'system', 'content':'Please summarize this message: '+txt}]
    #with open('debug/last_thinksummary.txt', 'w') as f:
    #    json.dump(prompt, f, indent=3)
    #short_txt = await gpt.gpt_get_answer(prompt)

    return speaker + ' thought about '+ txt + ', in the '+where_speaker_is


def summarize_fresh_move_memory(speaker, where_speaker_is, next_loc):
    """A summary of a memory of traveling. Can use open ai if desired, but it so simple it is not needed."""
    return speaker + ' travelled from the '+ where_speaker_is + ' to the '+ next_loc


######################## AI support functions #################################


async def len_limit(mem, numword):
    """Uses AI to limit the length of a message. If the AI fails to summarize the message, it will limit the length."""
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


async def append_simplify_memories(memories, new_memories, max_lengths=None, max_memories=64, num_compress=8):
    """
    Appends this memory to list-valued "the_memory".
    Summarizes memories to limit the length of older memories and the total number of memories.

    Parameters:
      memories: The list of memory strings.
      new_memories: New memories to be added to the list.
      max_lengths=None: Max per-memory length, in reverse chronological order.
        Generally a descending sequence as more recent memories are more detailed.
        The last element is used for all memories older than the lenght of this list.
        A default will be used if not supplied.
      max_memories=64: The maximum number of memories. This is a different limit than the per-memory limit.
      num_compress=8: If the number of memories exceeds max_memories, shrink it by this interval (by summarizing) untill it fits.

    Returns the new memory list.
    """

    memories.extend(new_memories)

    # Shorten single memories:
    if not max_lengths:
        max_lengths = [256, 128, 64, 32, 16, 8, 7, 6]
    max_lengths = max_lengths+[max_lengths[-1]]*len(memories)
    for i in range(len(memories)):
        age = len(memories)-i-1 # Zero for the most recent memory.
        numword = max_lengths[age]
        memories[i] = await len_limit(memories[i], numword)

    # Summarize multiple memories at a time if the total list grows too long:
    num_compress = 8
    if num_compress<1:
        num_compress = 1
    while len(memories) > max_memories:
        compressed_mem = await len_limit('\n'.join(memories[0:num_compress]))
        memories = [compressed_mem]+memories[num_compress+1:]

    return memories


class MMOWorld():
    """Contains locations, people, and places."""
    # TODO: JSON load and save.
    def __init__(self, locations=None, people=None):
        """
        A default starting world, or a world of your own.

        Parameters:
          locations: A dict from place name to description. Other characters can only hear and record memories in a given location.
          people: A dict from name to personality description.
        """
        if not locations:
            locations = {'dungeon':'You are bravely adventuring in a dungeon with monsters and treasure.',
                        'tavern':'You are in the tavern to get a drink.',
                        'academy':'You entered a classroom to learn about magic.',
                        'plaza':'You are outside in a town, walking to your next locale.'}
        _locs = list(locations.keys())
        if not people:
            people = {'Alice':'You love adventures, finding exploration in even the simplest of journeys.',
                      'Badr':'You are easily suprised, in both bad and good ways.',
                      'Kunal':'You are easily bored and rarely scared.',
                      'Charlie':'You often like to teach people about the history and creatures of this place, or about what they are talking about.',
                      'Omari':'You are quiet and tend to respond with single words and short phrases.',
                      'DoryFish':'You are happy, good natured, and excited.'}
        self.locations = locations
        self.people = people
        self.people_memories = {} # The memories of each person.
        self.people_where = {}
        for name in people.keys():
            self.people_where[name] = random.choice(_locs)
        self.speaker_history = [] # [speaker_name, spoken_mem, where_speaker_is]


    def get_prepend(self, use_reAct, location, speakers_here, speaker_name, has_memory):
        """This is the system part of the prompt that goes before the memory itself."""

        # Prompt engineering fun:
        #prepend = [{'role':'assistant', 'content':'You are participating in a conversation, what follows is a list of who spoke what. Please respond to it.'}] # Does NOT work well at all.
        #prepend = [{'role':'user', 'content':'you are simulating a conversation at a public Plaza in the afternoon.'}] # It makes them simulate a multi-party conversation.
        #prepend = [{'role':'user', 'content':f'Please act as if you are a single person responding to the following conversation. Your name is {speaker}.'}] # Works ok.

        alone = len(speakers_here) == 1

        # https://app.wordware.ai/r/73fd941f-7127-47d3-a6a2-05d283274ea6
        if use_reAct:
            other_places = set(list(self.locations.keys()))
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

    Your name is {speaker_name}. {self.locations[location]} You are also in a conversation with others.

    Behave as a single person would behave.

    {new}

    ## Personality

    Your personality is as follows: {self.people[speaker_name]}

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
            first_message = self.locations[location]
            if alone:
                if not has_memory:
                    first_message = first_message + f' Please speak your thoughts about this place you are in.'
                else:
                    first_message = first_message + f' Your name is {speaker_name}.'
            else:
                if not has_memory:
                    first_message = first_message + f' You are with other people. Please tell them about something that this place reminds you of. Your name is {speaker_name}.'
                else:
                    first_message = first_message + f' Your name is {speaker_name}. You are with other people and are responding to the following conversation.'
            first_message = first_message + self.people[speaker_name]
            prepend = [{'role':'system', 'content':first_message}]
        return prepend

    async def step_world(self, speaker_name=None, location=None, txt=None, is_reAct=False, send_message_f=None):
        """
        Takes a step in the conversation, updating the history and saving the message.
        Also people can move around.
        Both human or AI messages apply!

        Parameters:
           speaker_name=None: Who is speaking. If None will pick an AI charactger to speak.
           location=None: Where they are speaking. None will use the current NPC's location. 'all' will be heard in all locations.
           txt=None: The text they speak. None will use the AI to come up with the text.
           is_reAct=False: Special reAct mode (https://arxiv.org/pdf/2210.03629)
           send_message_f=None: Optional function (name, txt) of a string for sending messages at intermediate steps.
              Not async! But it can still call an asyncio task to be scheduled for non-blocking usage.
        """
        names = sorted(list(self.people.keys()))

        if not speaker_name:
            # Round-robin speakers:
            if self.speaker_history:
                last_speaker = self.speaker_history[-1][0]
            else:
                last_speaker = 'no last speaker'
            if last_speaker in names:
                speaker_name = (names+[names[0]])[names.index(last_speaker)+1]
            else:
                speaker_name = names[0]
        if not speaker_name in self.people and not txt:
            raise Exception("AI but no speaker speaking.")

        if location:
            where_speaker_is = location
        else:
            where_speaker_is = self.people_where[speaker_name]
        speakers_here = []
        for name in names:
            if self.people_where[name] == where_speaker_is or where_speaker_is=='all':
                speakers_here.append(name)

        is_ai = not txt
        observation_mem = None
        thought_mem = None
        spoken_words = ''; spoken_mem = None
        next_loc = None
        move_mem = None
        if is_ai: # Use AI to determine the txt.

            speaker_memory = self.people_memories.get(speaker_name, [])

            prepend = self.get_prepend(is_reAct, where_speaker_is, speakers_here, speaker_name, len(speaker_memory) > 0)

            # Load the memory:
            #the_messages = prepend+[{'role':'user', 'user_id':who, 'content':txt} for who, txt, where in speaker_memory]
            the_messages = prepend+[{'role':'user', 'content':mem} for mem in speaker_memory]

            if send_message_f:
                send_message_f(speaker_name, '<thinking>')
            gpt_txt = await gpt.gpt_get_answer(the_messages)
            with open('debug/debug_last_prompt.txt', 'w') as f:
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
                        spoken_words = p.replace('Speech:','')
                    if p.startswith('Action:'):
                        p = p.replace('Action:','')
                        next_loc = _maybe_moving_to(where_speaker_is, p, list(self.locations.keys()))
            else:
                txt = gpt_txt
                spoken_words = txt
                crowd_score = len(speakers_here)/(len(self.people)+0.00001) # Higher chance of leaving crowded areas.
                move_chance = 0.05 + 0.45*crowd_score

                if random.random()<=move_chance: # Move after speaking.
                    next_loc = random.choice(list(self.locations.keys()))
                    self.locations[speaker_name] = next_loc
        else:
            spoken_words = txt

        if spoken_words:
            if send_message_f and is_ai:
                send_message_f(speaker_name, spoken_words)
            self.speaker_history.append([speaker_name, spoken_words, where_speaker_is])
            spoken_mem = summarize_fresh_spoken_memory(speaker_name, where_speaker_is, spoken_words)
        if observation_mem:
            observation_mem = summarize_fresh_observation_memory(speaker_name, where_speaker_is, observation_mem)
        if thought_mem:
            thought_mem = summarize_fresh_thought_memory(speaker_name, where_speaker_is, thought_mem)
        if next_loc and next_loc != where_speaker_is:
            move_mem = summarize_fresh_move_memory(speaker_name, where_speaker_is, next_loc)

        # Store the memory:
        new_mems = {} # Name to list of new memories.
        for i, new_memory in enumerate([observation_mem, thought_mem, spoken_mem, move_mem]):
            if new_memory:
                new_mems[speaker_name] = new_mems.get(speaker_name, []) + [new_memory.replace(speaker_name, 'I')]
                if i in [2, 3]: # Spoken and move memories can be "seen" by others in the place (note: for now they see who left, not who entered).
                    for name in speakers_here:
                        if name != speaker_name:
                            new_mems[name] = new_mems.get(name, []) + [new_memory]

        mems_tasks = {}
        for name, v in new_mems.items():
            if name != 'DoryFish': # Finding Nemo
                mems_tasks[name] = append_simplify_memories(memories=self.people_memories.get(name, []), new_memories=v)

        if len(mems_tasks) > 0:
            send_message_f(None, f'<{list(mems_tasks.keys())} are consolidating thier memories>')
        mems_consolidated = dict(zip(mems_tasks.keys(), await asyncio.gather(*mems_tasks.values())))

        for name, v in mems_consolidated.items():
            self.people_memories[name] = v

        if next_loc and next_loc != where_speaker_is and send_message_f:
            send_message_f(speaker_name, 'I moved from the: '+where_speaker_is+' to the: '+next_loc)

        if next_loc and speaker_name in self.people:
            self.people_where[speaker_name] = next_loc

        if send_message_f:
            send_message_f(None, 'The AI step has been completed')

    def to_dict(self):
        """Convert the world to and from a dict for storage to the disk."""
        out = {}
        for ky in ['locations', 'people', 'people_memories', 'people_where', 'speaker_history']:
            out[ky] = getattr(self, ky)
        return out


def from_dict(d):
    """Convert the world to and from a dict for storage to the disk."""
    out = MMOWorld()
    for ky in ['locations', 'people', 'people_memories', 'people_where', 'speaker_history']:
        setattr(out, ky, d[ky])
    return out
