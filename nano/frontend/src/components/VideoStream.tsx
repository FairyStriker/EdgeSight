import { useEffect, useRef, useState } from "react";

/**
 * MJPEG 스트림(/video_feed)을 <img>로 표시.
 * onError 시 querystring을 갱신해 자동 재연결한다.
 */
export function VideoStream() {
  const [src, setSrc] = useState(`/video_feed?t=${Date.now()}`);
  const retryRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (retryRef.current) clearTimeout(retryRef.current);
    };
  }, []);

  const handleError = () => {
    if (retryRef.current) clearTimeout(retryRef.current);
    retryRef.current = window.setTimeout(() => {
      setSrc(`/video_feed?t=${Date.now()}`);
    }, 1500);
  };

  return (
    <div className="video-section">
      <img src={src} alt="CCTV Stream" onError={handleError} />
    </div>
  );
}
