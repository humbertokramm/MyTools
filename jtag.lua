comport = arg and arg[2] or "COM13"  -- fallback se não passar
project = arg and arg[1]

if project == "pd4202" then
	ju_hw2:card_init(comport)
	ju_hw2:voltage_force_start("A")
	ju_hw2:write_pin_probe(0,1,false)
	ju_hw2:write_pin_probe(1,0,false)
	ju_hw2:write_pin_probe(3,0,false)
	ju_hw2:write_pin_probe(4,1,false)
	ju_hw2:write_pin_probe(5,0,false)
	ju_hw2:write_pin_probe(6,0,false)
	ju_hw2:set_pwr_chain(1,"1V8", false)
	ju_hw2:set_pwr_chain(2,"3V3", false)
	ju_hw2:set_pwr_chain(3,"2V5", false)
	ju_hw2:set_pwr_chain(4,"2V5", false)
end

if project == "pd4302" then
	ju_hw2:card_init(comport)
	luabridge:set_variable("product_code","800534251")
	luabridge:set_variable("serial","12345")
	dofile("temp\\tf_dm4820_48vs_tensao_bs.lua")
	pd34:enable_som_power(true)
	pd34:enable_som_reset(true)
	pd34:enable_switch(true)
	pd34:enable_fpga(true)
	ju_hw2:set_pwr_chain(1,"3V3")
	ju_hw2:set_pwr_chain(2,"3V3")
	ju_hw2:set_pwr_chain(3,"3V3")
	ju_hw2:set_pwr_chain(4,"2V5")
	
	-- Testar as tensões:
	ju_hw2:voltage_start("A")
	
	-- Ligar forçado
	ju_hw2:voltage_force_start("A")
end