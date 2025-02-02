/*
pcm.js - PCM encoder/decoder
*/
(function(factory){
    factory(window);
    if(typeof(define)=='function' && define.amd){
        define(function(){
            return PCMEncoder;
        });
    };
    if(typeof(module)=='object' && module.exports){
        module.exports=PCMEncoder;
    };
}(function(window){
"use strict";

var PCMEncoder=function(){
    this.sampleRate=16000;
    this.numChannels=1;
    this.bitDepth=16;
    this.samples=[];
};

PCMEncoder.prototype.encode=function(buffer){
    var length=buffer.length;
    var data=new Int16Array(length);
    for(var i=0;i<length;i++){
        data[i]=Math.min(1,Math.max(-1,buffer[i]))*0x7FFF;
    }
    this.samples.push(data.buffer);
};

PCMEncoder.prototype.decode=function(buffer){
    var view=new DataView(buffer);
    var length=buffer.byteLength/2;
    var output=new Float32Array(length);
    for(var i=0;i<length;i++){
        var int=view.getInt16(i*2,true);
        output[i]=int/0x7FFF;
    }
    return output;
};

PCMEncoder.prototype.finish=function(){
    var dataLength=0;
    for(var i=0;i<this.samples.length;i++){
        dataLength+=this.samples[i].byteLength;
    }
    
    var buffer=new ArrayBuffer(dataLength);
    var view=new DataView(buffer);
    
    var offset=0;
    for(var i=0;i<this.samples.length;i++){
        var sample=new Uint8Array(this.samples[i]);
        for(var j=0;j<sample.length;j++){
            view.setUint8(offset,sample[j]);
            offset++;
        }
    }
    
    return buffer;
};

window.PCMEncoder=PCMEncoder;
}));
