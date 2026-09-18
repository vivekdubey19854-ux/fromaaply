const express=require('express');
const app=express();
app.use(express.urlencoded({extended:true}));
app.use(express.static(__dirname+'/public'));
let otp='000000';
app.get('/generate-otp',(req,res)=>{otp=String(Math.floor(100000+Math.random()*900000));console.log(`DEMO OTP: ${otp}`);res.json({sent:true});});
app.post('/submit',(req,res)=>{const captcha=String(req.body.captcha||'').replace(/\s+/g,'').toUpperCase();const ok=req.body.otp===otp&&captcha==='7X9K2';res.status(ok?200:400).send(`<h2>${ok?'Application Submitted':'Submission failed'}</h2><p>${ok?'The local demo accepted the user-supplied OTP/CAPTCHA.':'OTP or CAPTCHA was incorrect.'}</p>`);});
const port=Number(process.env.PORT||5000);app.listen(port,()=>console.log(`Formwise demo target: http://localhost:${port}`));
