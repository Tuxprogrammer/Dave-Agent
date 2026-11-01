// @description: Nearest GregTech ore veins containing an ore (e.g. "Naquadah", "Iron"), from the veins VisualProspecting recorded as chunks generated, with {waypoint:} links at the vein centre.
// @mode: read
// @side: server
// @timeout_ms: 3000
// @param ore: string, required. Ore material or vein name fragment: "naquadah", "magnetite", "oilsands"
// @param dim: number. Dimension (default the asker's, else 0)
// @param limit: number. How many veins (default 3, max 20)
// @param depleted: boolean. Include veins marked depleted (default false)
//
// Sources: VisualProspecting 1.5.42 ServerCache.instance (database/ServerCache.java:35) extends WorldCache, whose
// protected Int2ObjectMap<DimensionCache> `dimensions` (WorldCache.java:23) holds DimensionCache.getAllOreVeins()
// (DimensionCache.java:477) of OreVeinPosition (public chunkX, chunkZ, veinType; isDepleted(), getBlockX(),
// getBlockZ(); database/OreVeinPosition.java). VeinType has public name, minBlockY, maxBlockY, primaryOre,
// secondaryOre, inBetweenOre, sporadicOre (IOreMaterial: getInternalName(), getLocalizedName()), getVeinName().
// VP's own LogicalServer.getOreVein(dim, blockX, blockZ) passes block coords as chunk coords, so it is not used.
// GT itself keeps no saved vein list (GTWorldgenerator re-rolls them), so VP is the record.

def want = (params.ore ?: '').toString().toLowerCase().trim()
if (!want) return [error: 'give ore']
int dim = params.dim != null ? (params.dim as int) : (player?.dimension ?: 0)
int limit = Math.min(20, (params.limit ?: 3) as int)
boolean includeDepleted = params.depleted in [true, 'true']

def cache
try { cache = dave.cls('com.sinthoras.visualprospecting.database.ServerCache').instance }
catch (Throwable e) { return [error: 'VisualProspecting is not installed on this server'] }
def dims = dave.get(cache, 'dimensions')
def dc = dims.get(dim)
if (dc == null) return [found: 0, note: "VisualProspecting has no ore veins recorded for dimension ${dim}"]

def oreNames = { vt ->
    [vt.primaryOre, vt.secondaryOre, vt.inBetweenOre, vt.sporadicOre].findAll { it != null }.collect { m ->
        def n = []
        try { n << m.getInternalName() } catch (Throwable ignored) { }
        try { n << m.getLocalizedName() } catch (Throwable ignored) { }
        n
    }.flatten().findAll { it }
}
double px = player != null && player.dimension == dim ? player.posX : 0
double pz = player != null && player.dimension == dim ? player.posZ : 0
def hits = []
int scanned = 0
for (v in dc.getAllOreVeins()) {
    scanned++
    def vt = v.veinType
    if (vt == null || vt.name == null) continue
    if (!includeDepleted && v.isDepleted()) continue
    def names = oreNames(vt)
    String veinName = vt.name
    try { veinName = vt.getVeinName() ?: vt.name } catch (Throwable ignored) { }
    if (!(names + [vt.name, veinName]).any { it.toLowerCase().contains(want) }) continue
    double dx = v.getBlockX() - px, dz = v.getBlockZ() - pz
    int y = ((vt.minBlockY + vt.maxBlockY) / 2) as int
    hits << [vein: veinName, ores: names.unique(), x: v.getBlockX(), y: y, z: v.getBlockZ(), dim: dim,
             yRange: "${vt.minBlockY}-${vt.maxBlockY}", depleted: v.isDepleted(),
             distance: Math.round(Math.sqrt(dx * dx + dz * dz)),
             waypoint: dave.waypoint(v.getBlockX(), y, v.getBlockZ(), dim, veinName), d2: dx * dx + dz * dz]
}
hits.sort { it.d2 }
[found: hits.size(), veinsRecorded: scanned, shown: hits.take(limit).collect { it.findAll { k, x -> k != 'd2' } },
 note: (player != null && player.dimension == dim ? 'Distance from the asker.' : 'Distance from 0,0 (asker not in this dimension).') +
   ' Only veins in chunks generated while VisualProspecting was installed (or rescanned) are known.']
