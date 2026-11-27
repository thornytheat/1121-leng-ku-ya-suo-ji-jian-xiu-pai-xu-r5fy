function svgNode(tag, attributes, label) {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    if (label !== undefined) element.textContent = text(label);
    return element;
}

function figure(target, width, height) {
    const svg = svgNode('svg', {viewBox:`0 0 ${width} ${height}`, role:'img', 'aria-label':target.dataset.axis});
    target.append(svg);
    return svg;
}

function drawProjectChart(target, points) {
    const svg = figure(target, 630, 240);
    if (!points.length) return;
    const maxValue = Math.max(...points.map(i => Math.abs(i.value)), 1);
    const coordinates = points.map((point, i) => [43 + i * 540 / Math.max(1, points.length - 1), 191 - Math.abs(point.value) / maxValue * 135]);
    [56, 90, 124, 158, 192].forEach(y => svg.append(svgNode('line',{x1:42,x2:596,y1:y,y2:y,class:'chart-grid'})));
    svg.append(svgNode('polyline',{points:coordinates.map(pair=>pair.join(',')).join(' '),class:'series-line'}));
    coordinates.forEach(([x,y],i) => {
        const dot = svgNode('circle',{cx:x,cy:y,r:5,class:'chart-dot'});
        dot.append(svgNode('title',{},`${points[i].label} ${text(points[i].value)}`));
        svg.append(dot);
        if (i % 2 === 0) svg.append(svgNode('text',{x,y:222,'text-anchor':'middle',class:'chart-caption'},points[i].label.slice(0,9)));
    });
}
