ERROR_STATUS_INT = -1
number_of_bytes  = 4
ERROR_STATUS     = ERROR_STATUS_INT.to_bytes(byteorder="little",length=number_of_bytes,signed=True)
# 
SUCCESS_STATUS_INT = 0
SUCCESS_STATUS     = SUCCESS_STATUS_INT.to_bytes(byteorder="little",length=number_of_bytes,signed=True)