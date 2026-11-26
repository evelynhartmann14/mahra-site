import React from 'react';
import {AbsoluteFill, OffthreadVideo, Img, staticFile, useCurrentFrame, useVideoConfig, spring, interpolate, Sequence} from 'remotion';
import '@fontsource/cormorant-garamond/600.css';
import '@fontsource/cormorant-garamond/600-italic.css';
import '@fontsource/montserrat/800.css';
import '@fontsource/montserrat/600.css';
import '@fontsource/poppins/700.css';
import '@fontsource/playfair-display/700.css';

export type Word = {text: string; start: number; end: number};
export type Title = {text: string; start: number; end: number};
export type ReelProps = {
  video: string;            // file name inside public/
  fgVideo?: string;         // optional cut-out person (BEN2, webm with alpha) for text-behind-subject
  words: Word[];
  titles: Title[];          // big headline overlays
  durationSec: number;
  fps: number;
  width: number;
  height: number;
  style: 'elegante' | 'tiktok';
  logo?: string;            // file in public/
  cta?: string;             // closing call to action
  ctaSec?: number;          // how long the CTA shows at the end
  maxWordsPerLine: number;
  captionY: number;         // 0..1 vertical position of captions
  colors: {primary: string; accent: string; light: string; text: string};
  fontTitle: string;
  fontCaption: string;
};

export const defaultReelProps: ReelProps = {
  video: 'input.mp4',
  words: [],
  titles: [],
  durationSec: 10,
  fps: 30,
  width: 1080,
  height: 1920,
  style: 'elegante',
  cta: 'Compre pelo link na bio',
  ctaSec: 3,
  maxWordsPerLine: 4,
  captionY: 0.72,
  colors: {primary: '#8E0115', accent: '#C77A86', light: '#F4EFF0', text: '#FFFFFF'},
  fontTitle: 'Cormorant Garamond',
  fontCaption: 'Cormorant Garamond',
};

function groupWords(words: Word[], max: number): Word[][] {
  const out: Word[][] = [];
  let cur: Word[] = [];
  for (const w of words) {
    const prev = cur[cur.length - 1];
    const gap = prev ? w.start - prev.end : 0;
    const endsSentence = prev && /[.!?…]$/.test(prev.text);
    if (cur.length >= max || gap > 0.45 || endsSentence) {
      if (cur.length) out.push(cur);
      cur = [];
    }
    cur.push(w);
  }
  if (cur.length) out.push(cur);
  return out;
}

const Captions: React.FC<{p: ReelProps}> = ({p}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const groups = groupWords(p.words, p.maxWordsPerLine);
  const g = groups.find((gr) => t >= gr[0].start - 0.05 && t <= gr[gr.length - 1].end + 0.15);
  if (!g) return null;
  const pop = spring({frame: frame - Math.round(g[0].start * fps), fps, config: {damping: 14, stiffness: 180}});
  const tiktok = p.style === 'tiktok';
  return (
    <AbsoluteFill style={{justifyContent: 'flex-start', alignItems: 'center', top: `${p.captionY * 100}%`}}>
      <div style={{
        transform: `scale(${interpolate(pop, [0, 1], [0.85, 1])})`,
        display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: tiktok ? '0 22px' : '0 16px',
        maxWidth: p.width * 0.86, textAlign: 'center',
        fontFamily: p.fontCaption,
        fontWeight: tiktok ? 800 : 600,
        fontSize: tiktok ? 84 : 92, lineHeight: 1.08,
        textTransform: tiktok ? 'uppercase' : 'none',
      }}>
        {g.map((w, i) => {
          const active = t >= w.start && t <= w.end + 0.05;
          const spoken = t >= w.start;
          const color = tiktok
            ? (active ? p.colors.accent : p.colors.text)
            : (active ? p.colors.light : spoken ? p.colors.text : 'rgba(255,255,255,0.75)');
          return (
            <span key={i} style={{
              color,
              fontStyle: !tiktok && active ? 'italic' : 'normal',
              WebkitTextStroke: tiktok ? '10px #000' : undefined,
              paintOrder: 'stroke fill',
              textShadow: tiktok ? '0 6px 0 rgba(0,0,0,0.6)' : '0 4px 24px rgba(0,0,0,0.55), 0 2px 6px rgba(0,0,0,0.6)',
              background: !tiktok && active ? p.colors.primary : 'transparent',
              borderRadius: 14, padding: !tiktok ? '0 12px' : 0,
            }}>{w.text}</span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const Headline: React.FC<{text: string; p: ReelProps}> = ({text, p}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame, fps, config: {damping: 16}});
  return (
    <AbsoluteFill style={{justifyContent: 'flex-start', alignItems: 'center', paddingTop: p.height * 0.12}}>
      <div style={{
        fontFamily: p.fontTitle, fontStyle: p.fontTitle === 'Montserrat' ? 'normal' : 'italic', fontWeight: p.fontTitle === 'Montserrat' ? 800 : 600,
        fontSize: 150, lineHeight: 0.95, color: p.colors.light, textAlign: 'center',
        maxWidth: p.width * 0.9, opacity: s, transform: `translateY(${interpolate(s, [0, 1], [60, 0])}px)`,
        textShadow: '0 8px 40px rgba(0,0,0,0.45)',
      }}>{text}</div>
    </AbsoluteFill>
  );
};

const CTA: React.FC<{p: ReelProps}> = ({p}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame, fps, config: {damping: 15}});
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', background: p.colors.primary + Math.round(0xE6 * s).toString(16).padStart(2, '0'), backdropFilter: `blur(${12 * s}px)`}}>
      {p.logo ? <Img src={staticFile(p.logo)} style={{width: p.width * 0.62, marginBottom: 40, opacity: s}} /> : null}
      <div style={{
        fontFamily: p.fontTitle, fontWeight: 600, fontSize: 96, color: p.colors.light,
        textAlign: 'center', maxWidth: p.width * 0.85, textWrap: 'balance' as any, transform: `scale(${interpolate(s, [0, 1], [0.9, 1])})`, opacity: s,
      }}>{p.cta}</div>
      <div style={{marginTop: 40, width: interpolate(s, [0, 1], [0, 360]), height: 4, background: p.colors.accent}} />
    </AbsoluteFill>
  );
};

export const Reel: React.FC<ReelProps> = (p) => {
  const {fps} = useVideoConfig();
  const ctaFrames = Math.round((p.ctaSec ?? 0) * fps);
  const total = Math.round(p.durationSec * fps);
  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      <OffthreadVideo src={staticFile(p.video)} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
      {p.titles.map((ti, i) => (
        <Sequence key={i} from={Math.round(ti.start * fps)} durationInFrames={Math.max(1, Math.round((ti.end - ti.start) * fps))}>
          <Headline text={ti.text} p={p} />
        </Sequence>
      ))}
      {p.fgVideo ? <OffthreadVideo src={staticFile(p.fgVideo)} transparent style={{position: 'absolute', width: '100%', height: '100%', objectFit: 'cover'}} /> : null}
      <Sequence durationInFrames={Math.max(1, total - (p.cta ? ctaFrames : 0))}><Captions p={p} /></Sequence>
      {p.cta && ctaFrames > 0 ? (
        <Sequence from={Math.max(0, total - ctaFrames)}><CTA p={p} /></Sequence>
      ) : null}
    </AbsoluteFill>
  );
};
