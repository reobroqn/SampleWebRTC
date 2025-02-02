/*
recorder-core.js
*/
(function(factory){
    factory(window);
    if(typeof(define)=='function' && define.amd){
        define(function(){
            return Recorder;
        });
    };
    if(typeof(module)=='object' && module.exports){
        module.exports=Recorder;
    };
}(function(window){
"use strict";

var NOOP=function(){};
var Recorder=function(set){
    return new initFn(set);
};

// Initialize recorder
function initFn(set){
    this.set=set||{};
    this.buffer=[];
    this.bufferLength=0;
    this.state="inactive";
    this.sampleRate=this.set.sampleRate||16000;
}

// Start recording
initFn.prototype.start=function(){
    if(this.state!=="inactive"){
        throw new Error("Cannot start recording in "+this.state+" state");
    }
    this.state="recording";
    this.buffer=[];
    this.bufferLength=0;
};

// Stop recording
initFn.prototype.stop=function(){
    if(this.state==="inactive"){
        throw new Error("Cannot stop recording in inactive state");
    }
    this.state="inactive";
    return this.getWaveBlob();
};

// Get recorded data as WAV blob
initFn.prototype.getWaveBlob=function(){
    var sampleRate=this.sampleRate;
    var numChannels=1;
    var buffer=this.buffer;
    var length=this.bufferLength;
    
    // Create WAV header
    var header=new ArrayBuffer(44);
    var view=new DataView(header);
    
    // RIFF chunk descriptor
    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + length * 2, true);
    writeString(view, 8, 'WAVE');
    
    // FMT sub-chunk
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, numChannels * 2, true);
    view.setUint16(34, 16, true);
    
    // Data sub-chunk
    writeString(view, 36, 'data');
    view.setUint32(40, length * 2, true);
    
    // Create blob
    var blob=new Blob([header, buffer], {type: 'audio/wav'});
    return blob;
};

// Helper function to write strings to the header
function writeString(view, offset, string){
    for(var i=0;i<string.length;i++){
        view.setUint8(offset+i, string.charCodeAt(i));
    }
}

window.Recorder=Recorder;
}));
