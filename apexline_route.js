export const MAX_MAPBOX_WP = 23; // Mapbox max 25 coords; reserve 2 for start/end
export const MAX_GMAPS_WP  = 9;

export function haversineKm(lon1, lat1, lon2, lat2) {
  var R = 6371;
  var dLat = (lat2 - lat1) * Math.PI / 180;
  var dLon = (lon2 - lon1) * Math.PI / 180;
  var a = Math.sin(dLat/2)*Math.sin(dLat/2) +
          Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLon/2)*Math.sin(dLon/2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

export function segmentMidpoint(coords) {
  var total = 0;
  for (var i = 0; i < coords.length - 1; i++)
    total += haversineKm(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1]);
  var target = total / 2, cum = 0;
  for (var i = 0; i < coords.length - 1; i++) {
    var seg = haversineKm(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1]);
    if (cum + seg >= target) {
      var frac = seg > 0 ? (target - cum) / seg : 0;
      return [coords[i][0] + frac*(coords[i+1][0]-coords[i][0]),
              coords[i][1] + frac*(coords[i+1][1]-coords[i][1])];
    }
    cum += seg;
  }
  return coords[coords.length - 1];
}

// Insert a midpoint at the cheapest position in the route. Returns added km.
export function insertCheapest(route, mid) {
  var bestCost = Infinity, bestPos = 1;
  for (var i = 1; i < route.length; i++) {
    var prev = route[i-1], nxt = route[i];
    var added = haversineKm(prev[0],prev[1],mid[0],mid[1]) +
                haversineKm(mid[0],mid[1],nxt[0],nxt[1]) -
                haversineKm(prev[0],prev[1],nxt[0],nxt[1]);
    if (added < bestCost) { bestCost = added; bestPos = i; }
  }
  route.splice(bestPos, 0, mid);
  return bestCost;
}

// Returns { waypoints, overrunKm } — overrunKm > 0 means pinned roads exceeded budget.
export function greedyWaypoints(pinnedFeatures, scoredFeatures, start, end, budgetKm) {
  var route = [start, end];
  var usedKm = haversineKm(start[0], start[1], end[0], end[1]);
  var overrunKm = 0;

  // Insert pinned segments first, regardless of budget
  var pinnedMids = new Set();
  for (var pi = 0; pi < pinnedFeatures.length; pi++) {
    if (route.length - 2 >= MAX_MAPBOX_WP) break;
    var coords = pinnedFeatures[pi].geometry.coordinates;
    if (!coords || coords.length < 2) continue;
    var mid = segmentMidpoint(coords);
    var key = mid[0].toFixed(5) + ',' + mid[1].toFixed(5);
    if (pinnedMids.has(key)) continue;
    pinnedMids.add(key);
    var cost = insertCheapest(route, mid);
    usedKm += cost;
    if (usedKm > budgetKm) overrunKm = usedKm - budgetKm;
  }

  // Greedy fill with remaining budget
  var remainingKm = budgetKm - usedKm;
  for (var fi = 0; fi < scoredFeatures.length; fi++) {
    if (route.length - 2 >= MAX_MAPBOX_WP) break;
    var coords = scoredFeatures[fi].geometry.coordinates;
    if (!coords || coords.length < 2) continue;
    var mid = segmentMidpoint(coords);
    var key = mid[0].toFixed(5) + ',' + mid[1].toFixed(5);
    if (pinnedMids.has(key)) continue;

    var bestCost = Infinity, bestPos = 1;
    for (var i = 1; i < route.length; i++) {
      var prev = route[i-1], nxt = route[i];
      var added = haversineKm(prev[0],prev[1],mid[0],mid[1]) +
                  haversineKm(mid[0],mid[1],nxt[0],nxt[1]) -
                  haversineKm(prev[0],prev[1],nxt[0],nxt[1]);
      if (added < bestCost) { bestCost = added; bestPos = i; }
    }
    if (remainingKm >= bestCost) {
      route.splice(bestPos, 0, mid);
      remainingKm -= bestCost;
    }
  }
  return { waypoints: route, overrunKm: overrunKm };
}
