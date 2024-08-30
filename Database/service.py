from moobius import Moobius, MoobiusStorage, MoobiusWand
from moobius.types import MessageBody

class DbExampleService(Moobius):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def on_refresh(self, action):
        await self.send_message('Try sending some messages!', action.channel_id, action.sender, [action.sender])

    async def on_message_up(self, message):
        c_id = message.channel_id; sender = message.sender

        default_stats = {'str':1, 'dex':1, 'int':1}
        stats = self.channels[c_id].stats.get(sender, default_stats) # Self.channels is populated by Moobius using the db_config option within config.json.
        # It is also possible to manually instantiate MoobusStorage objects.

        report = ''
        if message.subtype == 'text':
            txt = message.content.text.lower().strip()
            for k in default_stats.keys():
                if txt == k:
                    stats[k] += 1; report = f'{k.upper()} increased to {stats[k]}'
            if not report:
                report = f'Current stats: {stats}; type in one of these stats to boost it by one point. These are saved to the disk using MoobiusStorage objects.'
        else:
            report = 'Send text messages to boost your stats.'
        self.channels[c_id].stats[sender] = stats # Important! This reassign keeps it loaded.
        await self.send_message(report, c_id, sender, [sender])

if __name__ == "__main__":
    MoobiusWand().run(DbExampleService, config='config/config.json')