# Users are bots attached to real user accounts.
# This is a different concept from puppet characters created by the service.


import sys, os, json, asyncio, time, pprint, traceback
import service

from dacite import from_dict
from loguru import logger
from moobius.types import MessageBody, ClickArgument
from moobius import Moobius, MoobiusStorage, types
from moobius import json_utils


this_folder = os.path.dirname(__file__)
tmp_file = this_folder + '/logs/reportsuser.json'

def clear_tmp_file():
    """Clears the tmp testing file. Called once at the beginning."""
    if os.path.exists(tmp_file):
        os.remove(tmp_file)
    with open(tmp_file,'w', encoding='utf-8') as f:
        json.dump([], f)


def save_to_tmp_file(x):
    """Saves (usally a test) to a temp file for automatic testing."""
    with open(tmp_file,'r', encoding='utf-8') as f:
        the_list = json.load(f)
    print(f"SAVING to user file. Current number of stored entries: {len(the_list)}")
    the_list.append(x)
    with open(tmp_file,'w', encoding='utf-8') as f:
        json_utils.enhanced_json_save(f, the_list)


####################################################################################################

class TestbedUser(Moobius):
    def __init__(self, **kwargs):
        clear_tmp_file() # VERY beginning!
        super().__init__(**kwargs)
        logger.info("I speak 中国人, English, and many other languages because I know Unicode!")
        self.all_tests_passed = False
        self.most_recent_updates = {} # Store the most recent updates to characters, canvas, etc. These can be queryed by sending a message to the user.
        self.channel_id2character_list = {} # The service must give the niceuser a character list.
        self.channel_id2test_state = {} # Dict from channel_id to {'fname':..., 'fstate':...}
        self.last_activity = {} # Last activity for each channel.
        self.last_refresh = {}
        self.received_evt_pairs = {} # Dict from channel id to pairs of [evt_type, ]. These accumulate and then periodically are cleared by main loop.

    async def main_listen_loop(self):
        """Wait, clear events, wait."""
        ch_ids = self.config['service_config'].get("channels", [])
        if not ch_ids:
            raise Exception("Channel ids not populated with non-empty list.")
        while True:
            if self.all_tests_passed:
                break # Tests are done, no need to listen.
            try:
                for ch_id in ch_ids:
                    tnow = time.time()
                    dt = tnow - self.last_activity[ch_id]
                    dtr = tnow - self.last_refresh[ch_id]
                    if dt > 16 and dtr > 16:
                        save_to_tmp_file(f"No recent activity refresh called, refreshing and resetting current test fn state, dt={dt}, ch={ch_id}, last_activity={self.last_activity}")
                        self.channel_id2test_state[ch_id]['fstate'] = None
                        self.last_refresh[ch_id] = time.time()
                        await self.send_refresh(ch_id)
                    evt_pairs = self.received_evt_pairs[ch_id]
                    self.received_evt_pairs[ch_id] = []
                    for event_type, event in evt_pairs:
                        await self.single_test_step(event_type, event)
            except Exception as e:
                logger.error("Testing loop bug:"+str(e))
                save_to_tmp_file(traceback.format_exc())
            await asyncio.sleep(1) # During any await, the queue of self.received_evt_pairs may be repopulated.

    async def single_test_step(self, event_type, event):
        """Runs one test step. Called in response to updates and message_downs sent to this usermode CCS"""
        if self.all_tests_passed:
            return
        event_type = event_type.lower().replace('-','_')
        channel_id = event.channel_id
        if channel_id not in self.channel_id2character_list:
            please_wait = f"Test must wait for channel_id2character_list[{channel_id}] to be filled evt ty = "+event_type
            logger.info(please_wait)
            save_to_tmp_file(please_wait)
            return
        all_users = self.channel_id2character_list[channel_id]

        ################### Finite state machine testing functions #############################s
        state_change_f_name_pairs = [] # [[f, name], [f, name], [f, name]]
        # Format of each test function:
        # f(current_state, +closure self, event_type, event) => True | Any.
        #   If is True, the test passes.

        async def testf(cur_state): # message_btn/Fancy Right Click.
            barg = ClickArgument(label="Bot", value="Fancy Right Click")
            simple_message_txt = "Will right click on this"
            if cur_state is None:
                cur_state = {}
            if event_type == 'on_update_menu':
                cur_state['the_menu_update'] = event
            if not cur_state.get('activated_menu'):
                await self.send_button_click(button_id='message_btn', channel_id=channel_id, button_args=[barg])
                save_to_tmp_file('Activated right click.')
                cur_state['activated_menu'] = True
                return cur_state
            if cur_state.get('the_menu_update') and not cur_state.get('sent_message'):
                await self.send_message(simple_message_txt, channel_id, sender=self.client_id, recipients=all_users+[self.client_id])
                cur_state['sent_message'] = True
                return cur_state
            if event_type == 'on_message_down':
                if event.content.text == simple_message_txt:
                    the_id = event.message_id
                    await self.send_menu_item_click(the_message=the_id, menu_item_id='2', channel_id=channel_id)
                if 'You choose ' in event.content.text and 'arguments=' in event.content.text:
                    save_to_tmp_file(event)
                    return True
            return cur_state
        state_change_f_name_pairs.append([testf, "right click menu test"])

        async def testf(cur_state): # Message with user data.
            user_data = {'foo':'bar', 'baz':[1, 'dos', '***', '....']}
            simple_message_txt = "This message should have user_data in it."
            if cur_state is None:
                await self.send_message(simple_message_txt, channel_id, sender=self.client_id, recipients=all_users+[self.client_id], user_data=user_data)
                cur_state = 'launched'
            if event_type == 'on_message_down':
                if event.content.text == simple_message_txt:
                    if event.user_data == user_data:
                        save_to_tmp_file(event)
                        return True
                    else:
                        save_to_tmp_file("User data mismatch; gold is:"+str(user_data)+" green is:"+str(event.user_data))
            return cur_state
        state_change_f_name_pairs.append([testf, "user data message test."])

        async def testf(cur_state): # Creating, pinging, and destroying a channel.
            # channel_btn/ "New Channel", "Ping Channels", "Leave Extra Channels", "List Bound Channels", "Fetch Channel List", "Update Extra Channels", "SDK direct download", "Channel Service ID"
            if not hasattr(self, '_tmp_cross_channel'):
                self._tmp_cross_channel = False # The state is defined per channel, so a global state is needed.
        state_change_f_name_pairs.append([testf, "channel test."])

        async def testf(cur_state): # Tests sending, getting, and reading a message.
            simple_message_txt = "Can this message be mark as read?"
            save_to_tmp_file("TMP debug read message test:"+str(cur_state))
            if cur_state is None:
                await self.send_message(simple_message_txt, channel_id, sender=self.client_id, recipients=all_users+[self.client_id]) # Self.client_id should be in all_users.
                return 'sent_out'
            elif cur_state == 'sent_out':
                if event_type == 'on_message_down':
                    the_id = event.message_id
                    old_readers = await self.fetch_message_readers(the_id) # Can send either the message or the id.
                    if not the_id:
                        save_to_tmp_file('No message_id on the message received: '+str(event))
                        return 'oops'
                    await self.send_mark_as_read(the_id)
                    await asyncio.sleep(3) # Seems to need time.
                    new_readers = await self.fetch_message_readers(the_id)
                    success = len(new_readers) > len(old_readers)
                    save_to_tmp_file("Old and new readers:"+str(old_readers)+'->'+str(new_readers))
                    if success:
                        return True
                    else:
                        save_to_tmp_file("No more new readers! Did this feature not work.")
                        return 'oops'
            return cur_state
        state_change_f_name_pairs.append([testf, "mark read test"])

        async def testf(cur_state):
            # Cur_state starts out None and becomes the returned state from this function.
            # Unless this returns True, which indicates the test worked and it's time to move on.
            barg = ClickArgument(label="Bot", value="Make Mickey")
            if event_type == 'on_message_down':
                if "limit of Mickey" in event.content.text:
                    save_to_tmp_file('Mickey limit, will have to wait and watch for Mickeys being built.')
                    return 'waiting for mickey' # This should not be hit in normal testing, only makes one mickey.
            elif event_type == 'on_update_characters':
                characters: list[types.Character] = [update_item.character for update_item in event.content]
                num_mickey = len([c for c in characters if 'mickey' in c.name.lower()])
                if num_mickey > 0: # Create mickey worked!
                    save_to_tmp_file(event) # Save the keystone events that pass the test.
                    return True
                else:
                    save_to_tmp_file(f"No mickeys, character names: {[c.name for c in characters]}")
            if cur_state is None:
                save_to_tmp_file('Make Mickey test sent out')
                await self.send_button_click(button_id='user_btn', channel_id=channel_id, button_args=[barg])
                return 'launched'
            return cur_state
        state_change_f_name_pairs.append([testf, "make mickey"])

        async def testf(cur_state): # Must be after Mickey talked.
            barg = ClickArgument(label="Bot", value="Mickey Talk")
            if event_type == 'on_message_down':
                if "Mickey" in event.content.text and "Here!" in event.content.text:
                    save_to_tmp_file(event)
                    return True
            if cur_state is None:
                save_to_tmp_file('Talk Mickey test sent out')
                await self.send_button_click(button_id='user_btn', channel_id=channel_id, button_args=[barg])
                return 'launched'
            return cur_state
        state_change_f_name_pairs.append([testf, "talk mickey"])

        async def testf(cur_state): # Reset mickeys.
            if event_type == 'on_update_characters':
                characters: list[types.Character] = [update_item.character for update_item in event.content]
                num_mickey = len([c for c in characters if 'mickey' in c.name.lower()])
                if num_mickey == 0: # Reset worked, no mickeys.
                    save_to_tmp_file(event)
                    return True
            if cur_state is None:
                await self.send_message('reset', channel_id=channel_id, sender=self.client_id, recipients="service")
                save_to_tmp_file('Reset Mickey test sent out')
                return 'launched'
            return cur_state
        state_change_f_name_pairs.append([testf, "reset mickey"])

        async def testf(cur_state): # Image message test.
            barg = ClickArgument(label="Bot", value="ImagePath")
            if cur_state is None:
                await self.send_button_click(button_id='message_btn', channel_id=channel_id, button_args=[barg])
                save_to_tmp_file('Image message request')
                return 'launched'
            if event_type == 'on_message_down':
                if event.content.path and event.subtype == types.IMAGE:
                    save_to_tmp_file(event)
                    return True # Image.
            return cur_state
        state_change_f_name_pairs.append([testf, "image button test"])

        async def testf(cur_state): # message_btn/Fetch Chat History.
            barg = ClickArgument(label="Bot", value="Fetch Chat History")
            if cur_state is None:
                await self.send_button_click(button_id='message_btn', channel_id=channel_id, button_args=[barg])
                save_to_tmp_file('Fetch history request.')
                return 'launched'
            if event_type == 'on_message_down':
                if 'Recent chat history' in event.content.text:
                    save_to_tmp_file(event)
                    return True
            return cur_state
        state_change_f_name_pairs.append([testf, "fetch chat history test"])

        ############################

        current_state = self.channel_id2test_state[channel_id]
        if not current_state['fname']:
            save_to_tmp_file('Initializing the current testing state.')
            current_state['fname'] = state_change_f_name_pairs[0][1]
            self.channel_id2test_state[channel_id] = current_state
        any_test = False
        for i, [f, nm] in enumerate(state_change_f_name_pairs):
            if current_state['fname'] == nm:
                any_test = True
                try:
                    result = await f(self.channel_id2test_state[channel_id]['fstate'])
                except Exception as e:
                    result = self.channel_id2test_state[channel_id]['fstate'] # No change.
                    save_to_tmp_file('Test Exception bug on: '+str(current_state)+'\n'+traceback.format_exc())
                if result is True: # The test passed. Start the next test.
                    save_to_tmp_file('Test PASSED:'+nm)
                    if i == len(state_change_f_name_pairs) - 1:
                        save_to_tmp_file('All tests completed and passed!')
                        self.all_tests_passed = True
                        return # Testing over!
                    self.channel_id2test_state[channel_id] = {'fname':state_change_f_name_pairs[i+1][1], 'fstate':None}
                else: # The test is still in progress, save the testing state.
                    self.channel_id2test_state[channel_id]['fstate'] = result
                break
        if not any_test:
            save_to_tmp_file('Orphaned state bug on: '+str(current_state))

    async def on_start(self):
        """Called after successful connection to Platform websocket and User login success."""
        # Startup:
        ch_ids = self.config['service_config'].get("channels", [])
        if not ch_ids:
            raise Exception("Channel ids not populated with non-empty list.")
        for ch_id in ch_ids:
            self.last_activity[ch_id] = -1e100
            self.last_refresh[ch_id] = -1e100
            self.received_evt_pairs[ch_id] = []
            self.channel_id2test_state[ch_id] = {'fname':None, 'fstate':None} 
        await self.user_join_service_channels() # Log into the default set of channels if not already.
        save_to_tmp_file("On start called")
        loop = asyncio.get_running_loop()
        loop.create_task(self.main_listen_loop())

    async def on_message_down(self, message_down: MessageBody):
        """Listen to messages the user sends and respond to them."""
        channel_id = message_down.channel_id
        content = message_down.content

        self.on_any_event('on_message_down', message_down)
        if message_down.sender == self.client_id:
            return # Avoid an infinite loop of responding to our messages.
        will_log_out = False
        jynx = False
        if message_down.subtype == types.TEXT:
            text0 = content.text
            text1 = text0.strip().lower()
            if text1 == "nya":
                text2 = "meow"
                jynx = True
                #button_list = [{"button_id": "keyc", "button_name": "cat talk","button_name": "Meow/Nya", "new_window": False}]
                #print('USER BUTTON UPDATE:', channel_id, [message_down.sender])
                #await self.send_buttons(button_list, channel_id, [message_down.sender]) # Does not work, not a service function.
            elif text1 == "meow":
                text2 = "nya"
            elif text1 == "log user out":
                text2 = "User logging out. Will not be usable until restart."
                will_log_out = True
            elif text1.startswith("rename user"):
                new_name = text1.replace("rename user",'').strip()
                the_user_id = self.client_id # Will not be needed for update_current_user in the .net version.
                logger.info('About to update the user\'s name!')
                file_path, rm_fn = service.make_local_image(vignette=0.0)
                await self.update_current_user(avatar=file_path, description='User got an updated name!', name=new_name)
                if rm_fn:
                    rm_fn()
                text2 = "renamed/reavatared the user (refresh)!"
            elif text1 == 'channel groups' or text1 == 'channel_groups':
                glist_temp = await self.fetch_channel_temp_group(channel_id)
                glist = await self.fetch_channel_group_list(channel_id)
                gdict = await self.http_api.fetch_channel_group_dict(channel_id, self.client_id)
                text2A = types.limit_len(f"Channel group list (this time from the user):\n{pprint.pformat(glist)}", 4096)
                text2B = types.limit_len(f"Channel group TEMP list (this time from the user):\n{pprint.pformat(glist_temp)}", 4096)
                text2C = types.limit_len(f"Channel group, dict form from User (used internally):\n{pprint.pformat(gdict)}", 4096)
                text2 = '\n\n'.join([text2A,text2B,text2C])
            elif text1 == 'show_updates' or text1 == 'show updates':
                update_lines = []
                for k, v in self.most_recent_updates.items():
                    update_lines.append(k+': '+str(v))
                show_JSON = False
                if show_JSON:
                    text2 = 'STR:\n'+'\n\n'.join(update_lines)+'\nJSON:\n'+json_utils.enhanced_json_save(None, self.most_recent_updates, indent=2)
                else:
                    text2 = '\n\n'.join(update_lines)
            elif text1 == 'user_info' or text1 == 'user info':
                try:
                    uinfo = await self.http_api.fetch_user_info()
                    text2A = "user info: "+str(uinfo)
                except Exception as e:
                    text2A = f'User info fetch fail: {e}'
                user_info1 = await self.fetch_character_profile(the_user_id) # Should be equal to self.user_info
                text2B = f" character profile (should be the same):\n{user_info1}"
                text2 = text2A + text2B
            elif text1 == 'mark read':
                messages = self.fetch_message_history(channel_id=channel_id, limit=64)
                tasks = [self.send_mark_as_read(m) for m in messages]
                await asyncio.gather(*tasks)
                text2 = f"Marked {len(tasks)} messages as read."
            elif text1 == 'mark unread':
                messages = self.fetch_message_history(channel_id=channel_id, limit=64)
                tasks = [self.send_mark_as_read(m, invert=True) for m in messages]
                await asyncio.gather(*tasks)
                text2 = f"Marked {len(tasks)} messages as unread."
            elif text1 == 'show readers':
                messages = self.fetch_message_history(channel_id=channel_id, limit=64)
                readerss_coru = [self.fetch_message_readers(message) for message in messages] # Readers.
                readerss = await asyncio.gather(*readerss_coru)
                text2 = 'User-ids who read each message:'+str(dict(zip([m.message_id for m in messages], readerss)))
            elif len(text0) > 160:
                text2 = f'Long message len={len(text0)}.'
            else:
                text2 = f"User repeat: {text0}"
            content.text = text2

        message_down.timestamp = int(time.time() * 1000)
        message_down.recipients = [message_down.sender]
        message_down.sender = self.client_id

        print('USER got a message. WILL SEND THIS MESSAGE (as message up); note conversion to/from recipient id vector:', message_down)
        await self.send_message(message_down)

        if jynx: # Again, with a non-existent id. Will it break?
            await asyncio.sleep(2)
            message_down.recipients = [message_down.sender, 'non-exist-id']
            await self.send_message(message_down)

        if will_log_out: # Log out after the message is sent.
            await self.sign_out()

    def on_any_event(self, evt_ty, evt):
        save_to_tmp_file('Event recieved:'+str(evt_ty)) # DEBUG.
        self.most_recent_updates[evt_ty] = evt # Debug use mainly.
        if not hasattr(evt, 'channel_id'):
            logger.error("No channel id for event: "+str(evt))
        channel_id = evt.channel_id
        self.last_activity[channel_id] = time.time()
        self.received_evt_pairs[channel_id].append([evt_ty, evt])

    #################### There are 5 on_update callbacks (not counting the generic on_update switchyard) ####################

    async def on_update_characters(self, update):
        self.on_any_event('on_update_characters', update)
        self.most_recent_updates['on_update_characters'] = update # Store this every update.
        character_ids = [e.character.character_id for e in update.content]
        self.channel_id2character_list[update.channel_id] = character_ids
        for character_id, character_profile in zip(character_ids, await self.fetch_character_profile(character_ids)):
            if not character_id:
                raise Exception('None character id.')
            if type(character_id) is not str:
                raise Exception('The characters in update should be a list of character ids.') # Extra assert just in case.
            c_id = update.channel_id

    async def on_update_buttons(self, update):
        self.on_any_event('on_update_buttons', update)

    async def on_update_canvas(self, update):
        self.on_any_event('on_update_canvas', update)

    async def on_update_channel_info(self, update):
        self.on_any_event('on_update_channel_info', update)

    async def on_update_menu(self, update):
        self.on_any_event('on_update_menu', update)

    ###########################################################################################################

    async def on_spell(self, text):
        """The user can also be tested with spells which call the self.send_... functions."""
        if type(text) is not str:
            logger.warning('User spell got non-string text')
        if text == "refresh":
            for channel_id in self.channels.keys():
                await self.refresh_socket(channel_id)
        elif text == "send_button_click_key1":
            for channel_id in self.channels.keys():
                await self.send_button_click("key1", [('arg1', "Meet Tubbs")], channel_id)
        elif text == "send_button_click_key2":
            for channel_id in self.channels.keys():
                await self.send_button_click("key2", [], channel_id)
        elif text == "nya_all":
            for channel_id in self.channels.keys():
                recipients = await self.fetch_member_ids()
                await self.send_message("nya nya nya", channel_id, recipients)
