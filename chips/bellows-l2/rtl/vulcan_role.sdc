# Bedrock defines the clocks. The DDR dcfifo instances provide their own
# pointer synchronizer constraints; both RAM data ports are locally clocked.
set src [get_registers -nowarn {*bellows_l1_ddr:*|native_online}]
set dst [get_registers -nowarn {*bellows_l1_ddr:*|online_sync[0]}]
if {[get_collection_size $src] > 0 && [get_collection_size $dst] > 0} {
    set_false_path -from $src -to $dst
}

set role_sync_clears [get_pins -compatibility_mode -nocase -nowarn {
    *bellows_l1_reset_sync:*|release_sync[*]|clrn
    *bellows_l1_ddr:*|dcfifo:*|*|dffpipe*:rdaclr|dff*|clrn
    *bellows_l1_ddr:*|dcfifo:*|*|dffpipe*:wraclr|dff*|clrn
}]
if {[get_collection_size $role_sync_clears] > 0} {
    set_false_path -to $role_sync_clears
}
unset src dst role_sync_clears
