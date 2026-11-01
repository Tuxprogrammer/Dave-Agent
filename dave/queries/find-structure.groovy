// @description: Where are generated structures (village, temple/pyramid/witch hut, mineshaft, stronghold, nether fortress) and dungeon spawners, nearest to the asker first, with {waypoint:} links. Structures from the world's saved structure data; spawners from loaded chunks.
// @mode: read
// @side: server
// @timeout_ms: 3000
// @param type: string. Village, Temple, Mineshaft, Stronghold, Fortress, Spawner, or all (default all)
// @param dim: number. Dimension (default the asker's, else 0). Fortresses are in the Nether (-1)
// @param limit: number. How many (default 5, max 30)
//
// Sources (vanilla 1.7.10, gtnh-src/minecraft): MapGenStructure.func_143027_a loads
// world.perWorldStorage.loadData(MapGenStructureData, name) with names "Temple", "Village", "Mineshaft",
// "Stronghold", "Fortress" (getStructureName in MapGenScatteredFeature:37, MapGenVillage:34, MapGenMineshaft:15,
// MapGenStronghold:55, MapGenNetherBridge:23). MapGenStructureData.func_143041_a() is the "Features" compound;
// each entry has "id", "ChunkX", "ChunkZ" and "BB" (int[6]: minX, minY, minZ, maxX, maxY, maxZ;
// StructureStart.java:52-69). perWorldStorage is a Forge field (real name at runtime). Spawners:
// TileEntityMobSpawner.func_145881_a() -> MobSpawnerBaseLogic.getEntityNameToSpawn().

def want = (params.type ?: 'all').toString().toLowerCase()
int dim = params.dim != null ? (params.dim as int) : (player?.dimension ?: 0)
int limit = Math.min(30, (params.limit ?: 5) as int)
def w = dave.world(dim)
if (w == null) return [error: "dimension ${dim} is not loaded"]
double px = player != null && player.dimension == dim ? player.posX : 0
double pz = player != null && player.dimension == dim ? player.posZ : 0

def hits = []
def dataClass = dave.cls('net.minecraft.world.gen.structure.MapGenStructureData')
for (name in ['Village', 'Temple', 'Mineshaft', 'Stronghold', 'Fortress']) {
    if (want != 'all' && want != name.toLowerCase()) continue
    def data = null
    try { data = w.perWorldStorage.loadData(dataClass, name) } catch (Throwable e) { }
    if (data == null) continue
    def features = data.func_143041_a()
    for (key in features.getKeySet()) {
        def tag = features.getCompoundTag(key)
        int[] bb = tag.getIntArray('BB')
        int x, y, z
        if (bb != null && bb.length == 6) {
            x = (bb[0] + bb[3]).intdiv(2); y = bb[1]; z = (bb[2] + bb[5]).intdiv(2)
        } else {
            x = tag.getInteger('ChunkX') * 16 + 8; y = 64; z = tag.getInteger('ChunkZ') * 16 + 8
        }
        String id = tag.getString('id') ?: name
        double dx = x - px, dz = z - pz
        hits << [kind: name, id: id, x: x, y: y, z: z, dim: dim, distance: Math.round(Math.sqrt(dx * dx + dz * dz)),
                 waypoint: dave.waypoint(x, y, z, dim, id), d2: dx * dx + dz * dz]
    }
}
if (want == 'all' || want == 'spawner') {
    for (te in dave.tiles(w)) {
        if (!(te instanceof TileEntityMobSpawner)) continue
        String mob = '?'
        try { mob = te.func_145881_a().getEntityNameToSpawn() } catch (ignored) { }
        double dx = te.xCoord - px, dz = te.zCoord - pz
        hits << [kind: 'Spawner', id: mob + ' spawner', x: te.xCoord, y: te.yCoord, z: te.zCoord, dim: dim,
                 distance: Math.round(Math.sqrt(dx * dx + dz * dz)),
                 waypoint: dave.waypoint(te.xCoord, te.yCoord, te.zCoord, dim, mob + ' spawner'), d2: dx * dx + dz * dz]
    }
}
hits.sort { it.d2 }
[found: hits.size(), shown: hits.take(limit).collect { it.findAll { k, v -> k != 'd2' } },
 note: (player != null && player.dimension == dim ? 'Distance from the asker.' : 'Distance from 0,0.') +
   ' Structures are those the world generated (many are off in GTNH); spawners only in loaded chunks.']
