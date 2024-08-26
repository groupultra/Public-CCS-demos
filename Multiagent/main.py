from service import NPCService
from moobius import MoobiusWand

if __name__ == "__main__":

    wand = MoobiusWand()

    handle = wand.run(NPCService, config="config/config.json", db_config="config/db.json", background=True)

    import time
    time.sleep(3)
    wand.spell(handle, 'THE SUPER SPELL')
