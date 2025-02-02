/*
wav.js - WAV encoder
*/
(function(factory){
    factory(window);
    if(typeof(define)=='function' && define.amd){
        define(function(){
            return WavEncoder;
        });
    };
    if(typeof(module)=='object' && module.exports){
        module.exports=WavEncoder;
    };
}(function(window){
"use strict";

var WavEncoder=function(){
    this.sampleRate=16000;
    this.numChannels=1;
    this.bytesPerSample=2;
    this.samples=[];
};

WavEncoder.prototype.encode=function(buffer){
    var length=buffer.length;
    var data=new Int16Array(length);
    for(var i=0;i<length;i++){
        data[i]=Math.min(1,Math.max(-1,buffer[i]))*0x7FFF;
    }
    this.samples.push(data.buffer);
};

WavEncoder.prototype.finish=function(){
    var dataLength=0;
    for(var i=0;i<this.samples.length;i++){
        dataLength+=this.samples[i].byteLength;
    }
    
    var buffer=new ArrayBuffer(44+dataLength);
    var view=new DataView(buffer);
    
    // Write WAV header
    writeString(view,0,"RIFF");
    view.setUint32(4,36+dataLength,true);
    writeString(view,8,"WAVE");
    writeString(view,12,"fmt ");
    view.setUint32(16,16,true);
    view.setUint16(20,1,true);
    view.setUint16(22,this.numChannels,true);
    view.setUint32(24,this.sampleRate,true);
    view.setUint32(28,this.sampleRate*this.bytesPerSample,true);
    view.setUint16(32,this.numChannels*this.bytesPerSample,true);
    view.setUint16(34,this.bytesPerSample*8,true);
    writeString(view,36,"data");
    view.setUint32(40,dataLength,true);
    
    // Write data
    var offset=44;
    for(var i=0;i<this.samples.length;i++){
        var sample=new Uint8Array(this.samples[i]);
        for(var j=0;j<sample.length;j++){
            view.setUint8(offset,sample[j]);
            offset++;
        }
    }
    
    return new Blob([buffer],{type:"audio/wav"});
};

function writeString(view,offset,string){
    for(var i=0;i<string.length;i++){
        view.setUint8(offset+i,string.charCodeAt(i));
    }
}

window.WavEncoder=WavEncoder;
}));
