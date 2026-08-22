import { useState, useRef, useCallback } from 'react';
import { medSyncApi } from '@/api/client';

export function useAudioStreamer(token, onTranscript, onToggles) {
  const wsRef = useRef(null);
  const audioCtxRef = useRef(null);
  const streamRef = useRef(null);
  const processorRef = useRef(null);
  const analyserRef = useRef(null);
  
  const [isStreaming, setIsStreaming] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [error, setError] = useState(null);

  const startStreaming = useCallback(async () => {
    try {
      setError(null);
      
      // Get microphone access
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      streamRef.current = stream;
      
      // Initialize AudioContext forcing 16kHz
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      const audioCtx = new AudioContext({ sampleRate: 16000 });
      audioCtxRef.current = audioCtx;
      
      const source = audioCtx.createMediaStreamSource(stream);
      
      // Analyser for UI visualizer
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;
      
      // Start a loop to update audio level
      const updateLevel = () => {
        if (!analyserRef.current) return;
        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
          sum += dataArray[i];
        }
        setAudioLevel(sum / dataArray.length);
        if (isStreaming || wsRef.current) {
          requestAnimationFrame(updateLevel);
        }
      };
      updateLevel();
      
      // ScriptProcessor for raw PCM extraction
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;
      
      // Setup WebSocket
      // Replace http with ws
      const wsUrl = medSyncApi.baseURL.replace(/^http/, 'ws') + `/encounter/${token}/audio-stream`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      
      ws.onopen = () => {
        setIsStreaming(true);
        // Connect nodes once WS is ready
        source.connect(processor);
        processor.connect(audioCtx.destination); // Required for Chrome to fire onaudioprocess
      };
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'TRANSCRIPT_CHUNK') {
            if (data.text) {
              onTranscript(data.text);
            }
            if (data.ui_toggles && Object.keys(data.ui_toggles).length > 0) {
              onToggles(data.ui_toggles);
            }
          }
        } catch (e) {
          console.error("WS message error", e);
        }
      };
      
      ws.onerror = (e) => {
        console.error("WebSocket error:", e);
        setError("WebSocket connection failed");
        stopStreaming();
      };
      
      ws.onclose = () => {
        setIsStreaming(false);
      };
      
      processor.onaudioprocess = (e) => {
        if (ws.readyState === WebSocket.OPEN) {
          const inputData = e.inputBuffer.getChannelData(0);
          // Convert float32 [-1, 1] to int16 [-32768, 32767]
          const pcm16 = new Int16Array(inputData.length);
          for (let i = 0; i < inputData.length; i++) {
            let s = Math.max(-1, Math.min(1, inputData[i]));
            pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
          }
          ws.send(pcm16.buffer);
        }
      };
      
    } catch (err) {
      console.error("Failed to start audio stream:", err);
      setError(err.message || "Microphone access denied");
      setIsStreaming(false);
    }
  }, [token, onTranscript, onToggles]);
  
  const stopStreaming = useCallback(() => {
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (analyserRef.current) {
      analyserRef.current.disconnect();
      analyserRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close();
      audioCtxRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    if (wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
      wsRef.current = null;
    }
    setIsStreaming(false);
    setAudioLevel(0);
  }, []);

  // Cleanup on unmount or token change
  useEffect(() => {
    return () => {
      stopStreaming();
    };
  }, [stopStreaming]);

  return { isStreaming, startStreaming, stopStreaming, audioLevel, error };
}
