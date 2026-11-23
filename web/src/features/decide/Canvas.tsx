import {useId} from 'react';
import type {CanvasSpec, CanvasEdge, CanvasNode} from './api';

// Same dimensions as the excalidraw-desk diagram style (white logo tile, pale groups, axis-aligned lines).
const TILE = 60;
const NODE_H = 110;
const ICON = 34;
const ABOVE = 10; // gap from the label baseline down to the line

type Box = {x: number; y: number; w: number; h: number};

function dataIcon(icons: CanvasSpec['icons'], name: string | null): string | null {
  if (!name) return null;
  const url = icons[name];
  return typeof url === 'string' && url.startsWith('data:') ? url : null;
}

function initial(name: string): string {
  const letter = [...name.trim()][0];
  return letter ? letter.toUpperCase() : '';
}

function nodeTile(node: CanvasNode): Box {
  return {x: node.cx - TILE / 2, y: node.top, w: TILE, h: TILE};
}

function Edge({edge, nodes, markerId}: {edge: CanvasEdge; nodes: Map<string, CanvasNode>; markerId: string}) {
  const from = nodes.get(edge.from);
  const to = nodes.get(edge.to);
  if (!from || !to) return null;
  const a = nodeTile(from);
  const b = nodeTile(to);
  const cls = `cv-edge cv-${edge.color ?? 'sub'}${edge.dashed ? ' cv-dashed' : ''}`;
  // Two diagrams can be on screen at once (front and back card); keep arrowhead ids per diagram.
  const marker = `url(#${markerId}-${edge.color ?? 'sub'})`;
  if (edge.kind === 'v') {
    const x = edge.x ?? from.cx;
    const down = b.y > a.y;
    const y1 = down ? from.top + NODE_H + 4 : a.y - 4;
    const y2 = down ? b.y - 4 : to.top + NODE_H + 4;
    return (
      <g>
        <line className={cls} x1={x} y1={y1} x2={x} y2={y2} markerEnd={marker} />
        {edge.label && <text className={`cv-label cv-${edge.color ?? 'sub'}-text`} x={x + 10} y={(y1 + y2) / 2 + 4}>{edge.label}</text>}
      </g>
    );
  }
  const y = edge.y ?? a.y + TILE / 2;
  const right = b.x >= a.x + a.w;
  const x1 = right ? a.x + a.w + 4 : a.x - 4;
  const x2 = right ? b.x - 4 : b.x + b.w + 4;
  return (
    <g>
      <line className={cls} x1={x1} y1={y} x2={x2} y2={y} markerEnd={marker} />
      {edge.label && <text className={`cv-label cv-${edge.color ?? 'sub'}-text`} x={(x1 + x2) / 2} y={y - ABOVE}
        textAnchor="middle">{edge.label}</text>}
    </g>
  );
}

function CanvasSvg({spec}: {spec: CanvasSpec}) {
  const markerId = `cv-arrow${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const [w, h] = spec.panel;
  const nodes = new Map((spec.nodes ?? []).map(node => [node.id, node]));
  return (
    <svg className="cv" viewBox={`0 0 ${w} ${h}`} width="100%" role="img" aria-label={spec.alt}>
      <defs>
        {(['main', 'sub', 'fail'] as const).map(color => (
          <marker key={color} id={`${markerId}-${color}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className={`cv-${color}-fill`} />
          </marker>
        ))}
      </defs>
      {spec.groups?.map(group => {
        const icon = dataIcon(spec.icons, group.icon);
        const tone = group.tone ?? 'neutral';
        return (
          <g key={`${group.x},${group.y}`}>
            <rect className={`cv-group cv-group-${tone}`} x={group.x} y={group.y} width={group.w} height={group.h} rx={10} />
            {icon
              ? <image href={icon} x={group.x + 12} y={group.y + 11} width={16} height={16} />
              : group.icon
                ? <text className={`cv-group-label cv-group-label-${tone}`} x={group.x + 20} y={group.y + 23} textAnchor="middle" aria-hidden="true">{initial(group.label)}</text>
                : null}
            <text className={`cv-group-label cv-group-label-${tone}`} x={group.x + (group.icon ? 34 : 12)} y={group.y + 24}>{group.label}</text>
          </g>
        );
      })}
      {spec.nodes?.map(node => {
        const tile = nodeTile(node);
        const icon = dataIcon(spec.icons, node.icon);
        return (
          <g key={node.id}>
            <rect className="cv-tile" x={tile.x} y={tile.y} width={TILE} height={TILE} rx={10} />
            {icon
              ? <image href={icon} x={node.cx - ICON / 2} y={node.top + (TILE - ICON) / 2} width={ICON} height={ICON} />
              : node.icon
                ? <text x={node.cx} y={node.top + TILE / 2} textAnchor="middle" dominantBaseline="central" fill="#1e1e1e" fontSize={28} aria-hidden="true">{initial(node.name)}</text>
                : null}
            <text className="cv-name" x={node.cx} y={node.top + 84} textAnchor="middle">{node.name}</text>
            {node.role && <text className="cv-role" x={node.cx} y={node.top + 102} textAnchor="middle">{node.role}</text>}
          </g>
        );
      })}
      {spec.edges?.map(edge => <Edge key={`${edge.from}-${edge.to}-${edge.kind}`} edge={edge} nodes={nodes} markerId={markerId} />)}
    </svg>
  );
}

/** Draw the diagram as SVG. It shrinks to the container width. */
export function Canvas({spec}: {spec: CanvasSpec}) {
  return <CanvasSvg spec={spec} />;
}
