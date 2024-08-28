import os
import click
import datetime
from flask import Flask, abort, redirect, send_file, url_for, make_response, request,render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, DateTime,update
from sqlalchemy.orm import mapped_column
from flask_simple_captcha import CAPTCHA
from PIL import Image
import io
from flask_compress import Compress

DEFAULT_CONFIG = {
    'SECRET_CAPTCHA_KEY': 'asdfwefsdvdasczxcvasdfczxvda',  # use for JWT encoding/decoding

    # CAPTCHA GENERATION SETTINGS
    'EXPIRE_SECONDS': 60 * 5,  # takes precedence over EXPIRE_MINUTES
    'CAPTCHA_IMG_FORMAT': 'JPEG',  # 'PNG' or 'JPEG' (JPEG is 3X faster)

    # CAPTCHA TEXT SETTINGS
    'CAPTCHA_LENGTH': 6,  # Length of the generated CAPTCHA text
    'CAPTCHA_DIGITS': False,  # Should digits be added to the character pool?
    'EXCLUDE_VISUALLY_SIMILAR': True,  # Exclude visually similar characters
    'BACKGROUND_COLOR': (0, 0, 0),  # RGB(A?) background color (default black)
    'TEXT_COLOR': (255, 255, 255),  # RGB(A?) text color (default white)

    # Optional settings
    #'ONLY_UPPERCASE': True, # Only use uppercase characters
    #'CHARACTER_POOL': 'AaBb',  # Use a custom character pool
}
SIMPLE_CAPTCHA = CAPTCHA(DEFAULT_CONFIG)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////' + os.path.join(app.root_path, 'data.db')
app = SIMPLE_CAPTCHA.init_app(app)
Compress(app)

db = SQLAlchemy(app)


def is_hexcolor(strhex:str):
    if not strhex:
        return False
    if len(strhex) != 6:
        return False
    for c in strhex:
        if c not in "0123456789abcdefABCDEF":
            return False
    return True

def hex_to_rgb(strhex:str):
    if is_hexcolor(strhex):
        return (int(strhex[0:2],16),int(strhex[2:4],16),int(strhex[4:6],16))
    else:
        raise ValueError(strhex)

class Canvas(db.Model):
    id = mapped_column(Integer,primary_key=True)
    name = mapped_column(String(60),unique=True)
    width = mapped_column(Integer,nullable=False)
    height = mapped_column(Integer,nullable=False)
    history = mapped_column(Boolean,nullable=False)
    data = mapped_column(JSON,nullable=False)
    
    def draw(self,x,y,color):
        # draw a pixel
        if not is_hexcolor(color):
            raise ValueError(color)
        if x >= self.width or y >= self.height:
            raise ValueError(x,y)
        if self.history:
            new = Draw(x=x,y=y,color=self.data[y][x],canvas_id=self.id)
            db.session.add(new)
        self.data[y][x]=color
        db.session.execute(update(Canvas).values(data=self.data))
        db.session.commit()
    
    def get_css(self):
        # get css
        css = ""
        for i in range(self.height):
            for j in range(self.width):
                css +="#p{} {{{}}} ".format(j+i*self.width,'background-color : #'+self.data[i][j])
        return css

    def get_pic(self):
        # get picture
        frame = Image.new("RGB",(self.width,self.height),color=(255,255,255))
        for i in range(self.width):
            for j in range(self.height):
                frame.putpixel((i,j),hex_to_rgb(self.data[j][i]))
        return frame
    
    def get_history(self):
        # get history gif
        if not self.history:
            return False
        gif = []
        data = self.data
        pixels = db.session.execute(db.select(Draw).filter_by(canvas_id=self.id).order_by(Draw.date.desc())).scalars()
        for pixel in pixels:
            frame = Image.new('RGB',(self.width,self.height),color=(255,255,255))
            data[pixel.y][pixel.x]=pixel.color
            for i in range(self.width):
                for j in range(self.height):
                    frame.putpixel((i,j),(hex_to_rgb(data[j][i])))
            gif.append(frame)
        return gif[::-1]

class Draw(db.Model):
    id = mapped_column(Integer,primary_key=True)
    x = mapped_column(Integer)
    y = mapped_column(Integer)
    color = mapped_column(String(6),nullable=False)
    date = mapped_column(DateTime,default=datetime.datetime.now(datetime.UTC))
    canvas_id = mapped_column(ForeignKey('canvas.id'),nullable=False)

@app.route("/")
def index():
    # show all canvas
    canvases = db.session.execute(db.select(Canvas)).scalars()
    return render_template("index.html",canvases=canvases)


@app.route("/draw/<int:id>/<int:pos>/",methods=['POST','GET'])
def draw(id,pos):
    canvas = db.get_or_404(Canvas,id)
    if pos > (canvas.width)*(canvas.height):
        abort(400)
    if request.method == 'GET':
        new_captcha_dict = SIMPLE_CAPTCHA.create()
        return render_template('draw.html', captcha=new_captcha_dict,canvas=canvas)
    if request.method == 'POST':
        c_hash = request.form.get('captcha-hash')
        c_text = request.form.get('captcha-text')
        if SIMPLE_CAPTCHA.verify(c_text, c_hash):
            canvas = db.get_or_404(Canvas,id)
            color = request.form.get('color')
            if is_hexcolor(color[1:]):
                canvas.draw(pos%canvas.width,int(pos/canvas.width),color[1:])
            else:
                print(color)
                abort(400)
            return redirect(url_for('output_html',id=canvas.id))
        else:
            abort(401)
    return

@app.get("/css/<int:id>")
def output_css(id):
    # output canvas data
    canvas = db.get_or_404(Canvas,id)
    res = make_response(canvas.get_css())
    res.content_type = 'text/css'
    return res

@app.get("/draw/<int:id>/")
def output_html(id):
    canvas = db.get_or_404(Canvas,id)
    return render_template('canvas.html',canvas=canvas)
 
@app.get('/img/<int:id>')
def get_img(id):
    canvas = db.get_or_404(Canvas,id)
    img_io = io.BytesIO()
    canvas.get_pic().save(img_io,'gif')
    img_io.seek(0)
    return send_file(img_io,mimetype='image/gif')

@app.get('/history/<int:id>')
def get_history(id):
    canvas = db.get_or_404(Canvas,id)
    gif_io = io.BytesIO()
    images=canvas.get_history()
    if images:
        images[0].save(gif_io,'gif',save_all = True, append_images = images[1:], optimize = False, duration = 500,loop=0)
        gif_io.seek(0)
        return send_file(gif_io,mimetype='image/gif')
    else:
        print(images)
        abort(404)

@app.cli.command("init")
def init():
    with app.app_context():
        db.create_all()
    click.echo('app inited')

@app.cli.command("add")
@click.argument("name")
@click.argument("width",type=int)
@click.argument("height",type=int)
@click.argument("history",type=bool)
@click.option("--fill")
def add(name,width,height,history,fill):
    with app.app_context():
        if not is_hexcolor(fill):
            click.echo('use ffffff')
            fill = 'ffffff'
        data = []
        for i in range(height):
            t = []
            for j in range(width):
                t.append(fill)
            data.append(t)
        canvas = Canvas(name=name,width=width,height=height,data=data,history=history)
        db.session.add(canvas)
        db.session.commit()
        click.echo('added')