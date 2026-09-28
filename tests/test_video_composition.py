import subprocess
import tempfile
import unittest
from pathlib import Path
from PIL import Image
import io
from core.processor.subtitles import _burn_ass, burn_subtitles

FFMPEG = Path(__file__).resolve().parents[1] / 'cli/ffmpeg.exe'

class CompositionTests(unittest.TestCase):
    def test_patch_inner_ratio_and_independent_text_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root/'source.mp4'
            subprocess.run([str(FFMPEG),'-v','error','-f','lavfi','-i',
                'color=blue:size=240x320:rate=1:duration=1,drawbox=x=0:y=0:w=240:h=160:color=red:t=fill',
                '-c:v','libx264','-pix_fmt','yuv420p',str(src)],check=True)
            srt=root/'imported.srt'
            srt.write_text('1\n00:00:00,000 --> 00:00:00,500\nTest\n',encoding='utf-8')
            ok,error=burn_subtitles(src,srt,root/'srt-result.mp4',str(FFMPEG),content_aspect='3x4',encode_device='cpu')
            self.assertTrue(ok,error)
            ass=root/'empty.ass' 
            ass.write_text('[Script Info]\nScriptType: v4.00+\nPlayResX: 240\nPlayResY: 320\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,0,0,0,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n',encoding='utf-8')
            def render(name,**kwargs):
                out=root/(name+'.mp4')
                ok,error=_burn_ass(src,ass,out,str(FFMPEG),encode_device='cpu',**kwargs)
                self.assertTrue(ok,error)
                result=subprocess.run([str(FFMPEG),'-v','error','-i',str(out),'-frames:v','1','-f','image2pipe','-vcodec','png','-'],capture_output=True,check=True)
                return Image.open(io.BytesIO(result.stdout)).convert('RGB')
            patch=render('patch',blur_original=True,blur_height_pct=.1,blur_width_pct=.8,blur_y_pct=.8,mask_config={'mode':'patch','source_x':.5,'source_y':.2})
            r,g,b=patch.getpixel((120,256));self.assertGreater(r,200);self.assertLess(b,50)
            self.assertGreater(patch.getpixel((120,220))[2],200)
            for blur in (False,True):
                im=render('ratio'+str(blur),target_aspect='9x16',content_aspect='3x4',aspect_pad_blur=blur)
                self.assertEqual(im.size,(1080,1920))
                self.assertGreater(im.getpixel((540,250))[0],200)
                self.assertGreater(im.getpixel((540,1660))[2],200)
            auto=render('auto',content_aspect='1x1');self.assertEqual(auto.size,(240,240))
            for mode in ('keep_width_crop_height', 'keep_height_crop_width'):
                cropped=render(mode,content_aspect='1x1',content_aspect_mode=mode)
                self.assertEqual(cropped.size,(240,240))
            layer={'type':'text','text':'TEST','x_pct':.5,'y_pct':.7,'size_pct':.12,'color':'#ffffff','box_color':'#00ff00','box_opacity':1,'text_opacity':0}
            hidden=render('hidden',video_overlays=[layer]);layer['text_opacity']=1
            visible=render('visible',video_overlays=[layer])
            green=lambda im:sum(1 for r,g,b in im.getdata() if g>180 and r<80 and b<80)
            white=lambda im:sum(1 for r,g,b in im.getdata() if min(r,g,b)>180)
            self.assertGreater(green(hidden),100)
            self.assertEqual(white(hidden),0)
            self.assertGreater(white(visible),50)

if __name__=='__main__':unittest.main()
