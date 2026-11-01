// @description: Where is a machine or block entity: GT machines by name or id, any other tile entity by block name or class, nearest to the asker first, with {waypoint:} links. Loaded chunks only.
// @mode: read
// @side: server
// @timeout_ms: 3000
// @param type: string, required. Name fragment: "blast furnace", "macerator", "multimachine.blastfurnace", "chest", "TileEntityFurnace"
// @param owner: string. Only GT machines owned by this player (GT records the placer)
// @param dim: number. Only this dimension
// @param limit: number. How many (default 5, max 25)
//
// Sources (GT5-Unofficial 5.09.54.265): IGregTechTileEntity.getMetaTileEntity(), getMetaTileID(), getOwnerName()
// (api/interfaces/tileentity/IGregTechTileEntity.java:40,50,110); IMetaTileEntity.getMetaName(), getLocalName()
// (IMetaTileEntity.java:284,620); pipes and cables are MetaPipeEntity (api/metatileentity/MetaPipeEntity.java:60).

def type = (params.type ?: '').toString().toLowerCase().trim()
if (!type) return [error: 'give type']
def owner = params.owner?.toString()?.toLowerCase()
Integer onlyDim = params.dim != null ? (params.dim as int) : null
int limit = Math.min(25, (params.limit ?: 5) as int)
def pipeClass = null
try { pipeClass = dave.cls('gregtech.api.metatileentity.MetaPipeEntity') } catch (ignored) { }

def hits = []
for (w in dave.worlds()) {
    int dim = w.provider.dimensionId
    if (onlyDim != null && dim != onlyDim) continue
    for (te in dave.tiles(w)) {
        def names = []
        String gtOwner = null
        def mte = null
        if (te.metaClass.respondsTo(te, 'getMetaTileEntity')) {
            mte = te.getMetaTileEntity()
            if (mte == null || (pipeClass != null && pipeClass.isInstance(mte))) continue
            try { names << mte.getLocalName() } catch (ignored) { }
            names << mte.getMetaName()
            gtOwner = te.getOwnerName()
        } else {
            names << te.getClass().getSimpleName()
            try {
                def block = te.getBlockType()
                def item = Item.getItemFromBlock(block)
                if (item != null) names << new ItemStack(item, 1, te.getBlockMetadata()).getDisplayName()
            } catch (ignored) { }
        }
        if (!names.any { it != null && it.toLowerCase().contains(type) }) continue
        if (owner && (gtOwner == null || gtOwner.toLowerCase() != owner)) continue
        double d2 = (player != null && player.dimension == dim)
            ? dave.dist2(player, te.xCoord + 0.5, te.yCoord + 0.5, te.zCoord + 0.5) : Double.MAX_VALUE
        String label = names.find { it } ?: type
        hits << [name: label, id: mte != null ? te.getMetaTileID() : null, owner: gtOwner, dim: dim,
                 x: te.xCoord, y: te.yCoord, z: te.zCoord,
                 distance: d2 == Double.MAX_VALUE ? null : Math.round(Math.sqrt(d2)),
                 waypoint: dave.waypoint(te.xCoord, te.yCoord, te.zCoord, dim, label), d2: d2]
    }
}
hits.sort { it.d2 }
[found: hits.size(), shown: hits.take(limit).collect { it.findAll { k, v -> k != 'd2' } },
 note: 'Only loaded chunks are searched (around online players and spawn); distance is from the asker, same dimension only.']
