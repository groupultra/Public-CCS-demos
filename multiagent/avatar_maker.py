# Makes avatar images.
import random, hashlib
from PIL import Image, ImageDraw

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
#make_image('test', 'test.png')
